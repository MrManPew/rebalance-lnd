import sys
from route_extension import RouteExtension
import rpc_pb2 as ln

MAX_ROUTES_TO_REQUEST = 80
ROUTE_REQUEST_INCREMENT = 20


def debug(message):
    sys.stderr.write(message + "\n")


class Routes:
    def __init__(self, lnd, pqr, payment_request, first_hop_channel_id, last_hop_channel):
        self.lnd = lnd
        self.pqr = pqr
        self.payment_request = payment_request
        self.first_hop_channel_id = first_hop_channel_id
        self.last_hop_channel = last_hop_channel
        self.all_routes = []
        self.returned_routes = []
        self.num_requested_routes = 0
        self.route_extension = RouteExtension(self.lnd, last_hop_channel, self.payment_request)

    def has_next(self):
        self.update_routes()
        return self.returned_routes < self.all_routes

    def get_next(self):
        self.update_routes()
        for route in self.all_routes:
            if route not in self.returned_routes:
                self.returned_routes.append(route)
                return route
        return None

    def update_routes(self):
        while True:
            if self.returned_routes < self.all_routes:
                return
            if self.num_requested_routes >= MAX_ROUTES_TO_REQUEST:
                return
            num_routes_to_request = self.num_requested_routes + ROUTE_REQUEST_INCREMENT
            num_routes_to_request = min(MAX_ROUTES_TO_REQUEST, num_routes_to_request)
            self.request_routes(num_routes_to_request)

    def request_routes(self, num_routes_to_request):

        # pqr testing override
        if False:
            routes = self.lnd.get_routes(self.last_hop_channel.remote_pubkey, self.get_amount(), num_routes_to_request)
        else:
            routes, costs, chans = self.pqr.pyqueryroutes(self.first_hop_channel_id,
                                                          self.last_hop_channel.remote_pubkey,
                                                          self.get_amount(),
                                                          num_routes_to_request)

            pqr_routes = []
            for j in range(len(routes)):
                route = routes[j]

                # when we use -f, the route will have been computed from that first hop onwards, so we need to re-add it
                if self.first_hop_channel_id:
                    first_hop = self.route_extension.create_new_hop(self.get_amount()*1000,
                                                    None,
                                                    self.lnd.get_current_height() + self.route_extension.get_expiry_delta_last_hop(),
                                                    pub_key=self.pqr.node_from_pubkey,
                                                    chan_id=self.first_hop_channel_id,
                                                    capacity=self.pqr.first_hop_capacity)
                    route_hops = [first_hop]
                else:
                    # when -f was not used, we computed routes from our own node, so no need to add an extra first hop here
                    route_hops = []

                # this takes all routes from pqr and turns them into proper series of ln.Hops
                for i in range(len(chans[j])):
                    amount_msat = self.get_amount()*1000
                    chan_id_name = int(chans[j][i]["name"][:-2])
                    chan_id_capacity = chans[j][i]["capacity"]


                    (_, pub_key_id) = self.pqr.g.es.select(name_eq=chans[j][i]["name"])[0].tuple
                    pub_key =  self.pqr.g.vs[pub_key_id]["name"]
                    new_hop = self.route_extension.create_new_hop(
                            amount_msat,
                            None,
                            self.lnd.get_current_height() + self.route_extension.get_expiry_delta_last_hop(),
                            pub_key=pub_key,
                            chan_id=chan_id_name,
                            capacity=chan_id_capacity)
                    route_hops.extend([new_hop])
                pqr_routes.extend([route_hops])
            routes = []
            for i in range(len(pqr_routes)):
                lnd_route = ln.Route(total_time_lock=pqr_routes[i][-1].expiry,
                                     total_fees=costs[i],
                                     total_fees_msat=costs[i] * 1000,
                                     total_amt=self.get_amount(),
                                     total_amt_msat=self.get_amount() * 1000,
                                     hops=pqr_routes[i])
                routes.extend([lnd_route])

        #f = open("pqr_routes.dat", "w+")
        #f.write("-- pqr routes below\n\n")

        #f = open("regular_routes.dat", "w+")
        #f.write("-- regular routes below\n\n")

        self.num_requested_routes = num_routes_to_request
        for route in routes:
            # in -t mode, add the last hop (back to us)
            # TODO: support -f only mode
            modified_route = self.add_rebalance_channel(route)
            chan_ids_along_the_route = [c.chan_id for c in modified_route.hops]
            #f.write("-- this route is %s\n" % chan_ids_along_the_route)
            #f.write("\n%s\n" % modified_route)
            #f.write("---\n---\n")
            self.add_route(modified_route)

        #f.close()


        #raw_input("did we make it there?")

    def add_rebalance_channel(self, route):
        return self.route_extension.add_rebalance_channel(route)

    def add_route(self, route):
        if route is None:
            return
        if route not in self.all_routes:
            self.all_routes.append(route)

    @staticmethod
    def print_route(route):
        route_str = " -> ".join(str(h.chan_id) for h in route.hops)
        return route_str

    def get_amount(self):
        return self.payment_request.num_satoshis
