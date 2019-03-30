# -*- coding: utf-8 -*-

# from https://gist.github.com/ALenfant/5491853


# TODO: precompute some weights for the pruned graph to be used with the built-in get_shortest_paths
# approach 1 (easier): compute path cost in both directions, take the max
#   TODO: make that a lot faster with numpy array operations
# approach 2 (harder, more accurate, still not perfect): switch to a directed graph, call channels chanid_1 and chanid_2 and compute the right weights associated
# approach 3: switch to a better algorithm handling dynamic edge cost ¯\_(ツ)_/¯

import numpy as np

class Yen:

    def __init__(self, lnd, graph, amount):
        self.lnd = lnd
        self.invoice_amount_sats = amount
        self.invoice_amount_msats = amount * 1000
        self.graph = graph
        self.graph.es["weight"] = self.get_bad_weights()
        self.working_graph = self.graph.copy()

    def display_channel_info(self, chan_id):
        # edge ID
        edge_id = self.graph.es.select(name_eq=chan_id)[0].index
        print "Information about %s (%s)" % (chan_id, edge_id)
        # node IDs and pubkeys
        (node_id_from, node_id_to) = self.graph.es[edge_id].tuple
        node_from = self.graph.vs[node_id_from]["name"]
        node_to = self.graph.vs[node_id_to]["name"]
        node_from_alias = self.graph.vs[node_id_from]["alias"].encode('ascii', 'ignore')
        node_to_alias = self.graph.vs[node_id_to]["alias"].encode('ascii', 'ignore')
        # fee base, fee rate
        fee_rate_milli_msat = self.graph.es[edge_id]["fee_rate_milli_msat"]
        base_fee_msat = self.graph.es[edge_id]["base_fee_msat"]
        # expected fee for the amount at stake
        expected_fee = self.graph.es[edge_id]["weight"]
        print "Connects %s (%s, %s)\n --> %s (%s, %s)" % (node_from, node_id_from, node_from_alias,
                                                          node_to, node_id_to, node_to_alias)
        print "base_fee_msat: %s, fee_rate_milli_msat: %s, expected_fee: %s" % (base_fee_msat, fee_rate_milli_msat, expected_fee)

    def display_node_info(self, node_pubkey):
            print "Searching for %s" % node_pubkey
            nodesearch = self.graph.vs.select(name_eq=node_pubkey)
            if len(nodesearch) == 0: print "no node found!"
            if len(nodesearch) > 1: print " ".join([n for n in nodesearch])
            node_id = self.graph.vs.select(name_eq=node_pubkey)[0].index
            node_alias = self.graph.vs[node_id]["alias"]
            print "Node is %s (node_id=%s, alias=%s)" % (node_pubkey, node_id, node_alias)

    def get_node_id_from_pubkey(self, node_pubkey):
            return self.graph.vs.select(name_eq=node_pubkey)[0].index

    def get_bad_weights(self):
        print "Computing %d naive weights" % len(self.graph.es)

        base_fee_msat_array = np.array(self.graph.es["base_fee_msat"])
        fee_rate_milli_msat_array = np.array(self.graph.es["fee_rate_milli_msat"])
        # the division by 1 million is because we use the amount in msats and the fee values are in msats too
        # then we want the array to be in sats, hence the last // 1000
        bad_weights_array = (25000 + base_fee_msat_array + fee_rate_milli_msat_array * self.invoice_amount_msats // 1000000) // 1000

        print "Done"

        """
        index = self.graph.es.select(name_eq="621690262665494528_2")[0].index
        print "Example: node #%d, name %s, from, to: %s, base_fee_msat: %s, fee_rate_milli_msat: %s" % (index,
                                    self.graph.es[index]["name"],
                                    [self.graph.vs[i]["name"] for i in list(self.graph.es[index].tuple)],
                                    base_fee_msat_array[index],
                                    fee_rate_milli_msat_array[index])
        print "Computed bad weight: %s" % bad_weights_array[index]
        raw_input("ok lor?")
        """
        return list(bad_weights_array)
        """
        print self.graph.es["base_fee_msat"]
        raw_input("ok with the base fee?")
        bad_weights = [0] * len(self.graph.es)
        for chan in self.graph.es:
            if chan.index % 1000 == 0: print chan.index
            #print chan
            node1 = self.graph.vs[chan.source]
            node2 = self.graph.vs[chan.target]
            fee1_msat = self.get_fee_msat(self.invoice_amount, chan["name"], node1["name"])
            fee2_msat = self.get_fee_msat(self.invoice_amount, chan["name"], node2["name"])
            fee_msat = max(fee1_msat, fee2_msat)
            bad_weights[chan.index] = fee_msat // 1000
        print "Done"
        return bad_weights
        """


    def nodes2channels(self, nodes, bother_display):

        channels = [None] * (len(nodes)-1)

        for i in range(len(nodes)-1):
            # select returns an EdgeSeq with one element here, so we take it and that's it
            # TODO: there may be 2+ nodes between two edges, so:
            # 1/ Either we pick one randomly here, based on capacity, fees etc
            # 2/ Or we need to have the pathfinding algorithm return not only a list of vertices, but with edges too
            # using output="epath"
            #chans = self.graph.es.select(_within=[nodes[i], nodes[i+1]])
            chans = self.graph.es.select(_source=nodes[i], _target=nodes[i+1])
            #if len(chans) != 1:
            #    print "chan betwen %s and %s gave funny stuff: %s" % (self.graph.vs[nodes[i]],
            #                                                          self.graph.vs[nodes[i+1]],
            #                                                          [c for c in chans])
            channels[i] = chans[0]

        if bother_display: print "Turned the following list of nodes:\n%s" % [self.graph.vs[n]["name"] for n in nodes]
        if bother_display:
            print "Into the following channels:"
            for c in channels: self.display_channel_info(c["name"])

        return channels

    def update_amounts(self, hops_nodes):
        """ This takes a path (as a list of vertices) and computes the total fees for each hop. The total cost of the path
        is found under the first hop since the whole thing must be forwarded.

        TODO: this now computes cost of a generic path.
        When computing loops for a real re-balance, the source chan ID and the target chan ID have to be added,
        depending on the -t or -f mode.
        """

        # flag to say whether we should even displaying information about that path. If it has loops, then no
        #bother_display = (len(set(hops_nodes)) == len(hops_nodes))
        bother_display = False

        # first, we need to turn a list of vertices (nodes) into a list of edges (channels)
        hops_channels = self.nodes2channels(hops_nodes, bother_display)


        additional_fees = 0
        amt_to_forward_msat_list = [self.invoice_amount_msats] * len(hops_channels)
        amt_to_forward_list = [0] * len(hops_channels)
        fee_msat_list = [0] * len(hops_channels)
        fee_list = [0] * len(hops_channels)

        hop_out_channel_id = hops_channels[-1] #self.rebalance_channel.chan_id
        #for hop in reversed(hops):
        for i in reversed(range(len(hops_channels))):

            #print hop_out_channel_id

            #amount_to_forward_msat = hop.amt_to_forward_msat + additional_fees
            amount_to_forward_msat = amt_to_forward_msat_list[i] + additional_fees
            amt_to_forward_msat_list[i] = amount_to_forward_msat
            #hop.amt_to_forward_msat = amount_to_forward_msat
            amt_to_forward_list[i] = amount_to_forward_msat // 1000
            #hop.amt_to_forward = amount_to_forward_msat // 1000

            fee_msat_before = fee_msat_list[i]
            #fee_msat_before = hop.fee_msat

            # Here the last parameter is the pubkey of the source of the hop.

            # the edge's name contains the suffix, so we need to remove it here
            new_fee_msat = self.get_fee_msat(amount_to_forward_msat, hop_out_channel_id["name"][:-2],
                                             self.graph.vs[hops_nodes[i+1]]["name"])
            #new_fee_msat = self.get_fee_msat(amount_to_forward_msat, hop_out_channel_id, hop.pub_key)
            fee_msat_list[i] = new_fee_msat
            #hop.fee_msat = new_fee_msat
            fee_list[i] = new_fee_msat // 1000

            if bother_display: print "hop_out_channel_id: %s, new_fee_msat: %s" % (hop_out_channel_id["name"], new_fee_msat)

            #hop.fee = new_fee_msat // 1000
            additional_fees += new_fee_msat - fee_msat_before
            hop_out_channel_id = hops_channels[i-1]
            #hop_out_channel_id = hop.chan_id

        if bother_display:
            print "amt_to_forward_msat_list: %s" % amt_to_forward_msat_list
            print "amt_to_forward_list: %s" % amt_to_forward_list
            print "fee_msat_list: %s" % fee_msat_list
            print "fee_list: %s" % fee_list
            print "fees from bad weights: %s" % ([h["weight"] for h in hops_channels])
        return fee_list

    def get_fee_msat(self, amount_msat, channel_id, source_pubkey):

        #print "amount_msat: %s, channel_id: %s, source_pubkey: %s" % (amount_msat, channel_id, source_pubkey)
        policy = self.lnd.get_policy(channel_id, source_pubkey)
        fee_base_msat = self.get_fee_base_msat(policy)
        fee_rate_milli_msat = self.get_fee_rate_msat(policy)
        fee_msat = fee_base_msat + fee_rate_milli_msat * amount_msat // 1000000
        #print "%s + %s * %s // 1000000 = %s" % (fee_base_msat, fee_rate_milli_msat, amount_msat, fee_msat)
        return fee_msat

    @staticmethod
    def get_time_lock_delta(policy):
        # sometimes that field seems not to be set -- interpret it as 0
        if hasattr(policy, "time_lock_delta"):
            return policy.time_lock_delta
        return int(0)

    @staticmethod
    def get_fee_base_msat(policy):
        # sometimes that field seems not to be set -- interpret it as 0
        if hasattr(policy, "fee_base_msat"):
            return int(policy.fee_base_msat)
        return int(0)

    @staticmethod
    def get_fee_rate_msat(policy):
        # sometimes that field seems not to be set -- interpret it as 0
        if hasattr(policy, "fee_rate_milli_msat"):
            return int(policy.fee_rate_milli_msat)
        return int(0)

    def path_cost(self, graph, path, weights=None):
        pathcost = 0

        # here the path is a list of vertices (nodes)
        # below is a Lightning Network implementation of dynamic fee computation


        pathcost = len(path)
        """
        for i in range(len(path)):
            if i > 0:
                #print "looking at %s to %s" % (path[i-1], path[i])
                #print graph.neighbors(path[i-1])
                #print graph.neighbors(path[i])
                #edge=graph.es.find(_source=path[i-1], _target=path[i])
                edge=graph.es.select((path[i-1], path[i]))
                #print "edge is %s" % edge
                if weights != None:
                    pathcost += edge[weights]
                else:
                    #just count the number of edges
                    pathcost += 1
        """
        fee_list = self.update_amounts(path)
        pathcost = sum(fee_list)


        return pathcost

    def yen_igraph(self, source, target, num_k, weights):

        import Queue

        #Shortest path from the source to the target
        A = [self.working_graph.get_shortest_paths(source, to=target, output="vpath", weights="weight")[0]]
        A_costs = [self.path_cost(self.working_graph, A[0], weights)]

        #Initialize the heap to store the potential kth shortest path
        B = Queue.PriorityQueue()

        for k in range(1, num_k):
            #The spur node ranges from the first node to the next to last node in the shortest path
            for i in range(len(A[k-1])-1):
                # Spur node is retrieved from the previous k-shortest path, k − 1
                spurNode = A[k-1][i]
                #The sequence of nodes from the source to the spur node of the previous k-shortest path
                rootPath = A[k-1][:i]

                #We store the removed edges
                removed_edges = []

                for path in A:
                    if len(path) - 1 > i and rootPath == path[:i]:
                        #Remove the links that are part of the previous shortest paths which share the same root path
                        edge = self.working_graph.es.select(_source=path[i], _target=path[i+1])
                        if len(edge) == 0:
                            continue #edge already deleted
                        edge = edge[0]
                        removed_edges.append((path[i], path[i+1], edge.attributes()))
                        edge.delete()

                #Calculate the spur path from the spur node to the sink
                spurPath = self.working_graph.get_shortest_paths(spurNode,
                                                                 to=target,
                                                                 output="vpath",
                                                                 weights="weight")[0]

                if len(spurPath) > 0:
                    #Entire path is made up of the root path and spur path
                    totalPath = rootPath + spurPath
                    totalPathCost = self.path_cost(self.working_graph, totalPath, weights)

                    # add the path only if there is no loop
                    if len(totalPath) == len(set(totalPath)):
                        #Add the potential k-shortest path to the heap
                        B.put((totalPathCost, totalPath))

                #Add back the edges that were removed from the graph
                for removed_edge in removed_edges:
                    node_start, node_end, cost = removed_edge
                    self.working_graph.add_edge(node_start, node_end,
                                                weight=cost["weight"],
                                                capacity=cost["capacity"],
                                                name=cost["name"],
                                                fee_rate_milli_msat=cost["fee_rate_milli_msat"],
                                                base_fee_msat=cost["base_fee_msat"])

            #Sort the potential k-shortest paths by cost
            #B is already sorted
            #Add the lowest cost path becomes the k-shortest path.
            while True:
                cost_, path_ = B.get()
                if path_ not in A and len(path_) < 8:
                    #We found a new path to add
                    A.append(path_)
                    A_costs.append(cost_)
                    break
                if len(path_) > 8:
                    print "skipped long path"

        return A, A_costs
