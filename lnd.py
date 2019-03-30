import os
from os.path import expanduser
import codecs
import grpc

import rpc_pb2 as ln
import rpc_pb2_grpc as lnrpc

SERVER = 'localhost:10009'
LND_DIR = expanduser("~/.lnd")
MESSAGE_SIZE_MB = 50 * 1024 * 1024


class Lnd:
    def __init__(self):
        os.environ['GRPC_SSL_CIPHER_SUITES'] = 'HIGH+ECDSA'
        combined_credentials = self.get_credentials(LND_DIR)
        channel_options = [
            ('grpc.max_message_length', MESSAGE_SIZE_MB),
            ('grpc.max_receive_message_length', MESSAGE_SIZE_MB)
        ]
        grpc_channel = grpc.secure_channel(SERVER, combined_credentials, channel_options)
        self.stub = lnrpc.LightningStub(grpc_channel)
        self.graph = None
        self.policies_cache = {}
        self.init_policies_cache()

    @staticmethod
    def get_credentials(lnd_dir):
        tls_certificate = open(lnd_dir + '/tls.cert', 'rb').read()
        ssl_credentials = grpc.ssl_channel_credentials(tls_certificate)
        macaroon = codecs.encode(open(lnd_dir + '/data/chain/bitcoin/mainnet/admin.macaroon', 'rb').read(), 'hex')
        auth_credentials = grpc.metadata_call_credentials(lambda _, callback: callback([('macaroon', macaroon)], None))
        combined_credentials = grpc.composite_channel_credentials(ssl_credentials, auth_credentials)
        return combined_credentials

    def get_info(self):
        return self.stub.GetInfo(ln.GetInfoRequest())

    def get_graph(self):
        if self.graph is None:
            self.graph = self.stub.DescribeGraph(ln.ChannelGraphRequest())
        return self.graph

    def get_own_pubkey(self):
        return self.get_info().identity_pubkey

    def get_current_height(self):
        return self.get_info().block_height

    def get_edges(self):
        return self.get_graph().edges

    def generate_invoice(self, memo, amount):
        invoice_request = ln.Invoice(
            memo=memo,
            value=amount,
        )
        add_invoice_response = self.stub.AddInvoice(invoice_request)
        return self.decode_payment_request(add_invoice_response.payment_request)

    def decode_payment_request(self, payment_request):
        request = ln.PayReqString(
            pay_req=payment_request,
        )
        return self.stub.DecodePayReq(request)

    def get_channels(self):
        request = ln.ListChannelsRequest(
            active_only=True,
        )
        return self.stub.ListChannels(request).channels

    def get_routes(self, pub_key, amount, num_routes):
        request = ln.QueryRoutesRequest(
            pub_key=pub_key,
            amt=amount,
            num_routes=num_routes,
        )
        response = self.stub.QueryRoutes(request)
        return response.routes

    def init_policies_cache(self):
        print "init policies cache"
        for edge in self.get_edges():
            key1 = str(edge.channel_id) + "_" + edge.node1_pub
            policy1 = edge.node1_policy
            key2 = str(edge.channel_id) + "_" + edge.node2_pub
            policy2 = edge.node2_policy
            self.policies_cache[key1] = policy1
            self.policies_cache[key2] = policy2
        print "done: length is %s" % len(self.policies_cache)

    def get_policy(self, channel_id, source_pubkey):
        # node1_policy contains the fee base and rate for payments from node1 to node2
        key = str(channel_id) + "_" + source_pubkey
        if key in self.policies_cache:
            return self.policies_cache[key]
        for edge in self.get_edges():
            if edge.channel_id == channel_id:
                if edge.node1_pub == source_pubkey:
                    result = edge.node1_policy
                    self.policies_cache[key] = result
                else:
                    result = edge.node2_policy
                    self.policies_cache[key] = result
                return result

    def send_payment(self, payment_request, routes):
        payment_hash = payment_request.payment_hash
        request = ln.SendToRouteRequest()

        request.payment_hash_string = payment_hash
        request.routes.extend(routes)

        return self.stub.SendToRouteSync(request)
