# pyqueryroutes
# an attempt at re-implementing a k-shortest path algorithm
# for source routing in lnd, giving more flexibility when 
# trying to build routes to rebalance channels (as used) in
# C-Otto/rebelance-lnd

from igraph import *
from yen_igraph import Yen

class PQR:

	def __init__(self, lnd):
		self.lnd = lnd
		lndgraph = lnd.get_graph()
		self.g = self.lndgraph2igraph(lndgraph, lnd)
		print summary(self.g)

	def get_graph(self):
		return self.g

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

	@staticmethod
	def lndgraph2igraph(graph, lnd):
		"""
		Creates an igraph Graph object with the following properties:
		- directed, so the edges will have names like chan_id<1> and chan_id<2>
		- properties: base_fee_msat, fee_rate_milli_msat (to compute weights later on), capacity
		"""
		lnd_nb_nodes = len(graph.nodes)
		lnd_nb_edges = len(graph.edges)
		print lnd_nb_nodes
		print lnd_nb_edges

		g = Graph(directed=True)
		g.add_vertices(lnd_nb_nodes)
		
		# add the vertices names
		print "Adding vertices' names"
		list_of_lnd_node_pubkeys = [n.pub_key for n in graph.nodes]
		list_of_lnd_node_aliases = [n.alias for n in graph.nodes]
		g.vs["name"] = list_of_lnd_node_pubkeys
		g.vs["alias"] = list_of_lnd_node_aliases

		# add the edges by node name
		print "Adding edges"
		g.add_edges([(e.node1_pub, e.node2_pub) for e in graph.edges] + [(e.node2_pub, e.node1_pub) for e in graph.edges])
		# add the channel ids as names
		print "Adding channel IDs"
		list_of_lnd_chan_id = [str(e.channel_id)+"_1" for e in graph.edges] + [str(e.channel_id)+"_2" for e in graph.edges]
		g.es["name"] = list_of_lnd_chan_id
		# add the capacity
		print "Adding capacity"
		list_of_lnd_chan_capacity = [e.capacity for e in graph.edges] * 2 # capacity goes both ways
		g.es["capacity"] = list_of_lnd_chan_capacity	
		# add the fee parameters
		print "Adding fee parameters"
		print "Get policies"
		policies = [lnd.get_policy(e.channel_id, e.node2_pub) for e in graph.edges]
		policies += [lnd.get_policy(e.channel_id, e.node1_pub) for e in graph.edges]
		print "Get base_fee_msat"
		list_of_base_fee_msat = [PQR.get_fee_base_msat(policy) for policy in policies]
		print "Get fee_rate_milli_msat"
		list_of_fee_rate_milli_msat = [PQR.get_fee_rate_msat(policy) for policy in policies]
		print "Add base_fee_msat"
		g.es["base_fee_msat"] = list_of_base_fee_msat
		print "Add fee_rate_milli_msat"
		g.es["fee_rate_milli_msat"] = list_of_fee_rate_milli_msat

		return g


	def subgraph_capacity(self, g, min=0, max=1e20):
		""" Returns a subgraph with capacities filtered between mix and max values.
		This helps reduce the size of the graph to find a path in"""
		# find valid edges
		subg_edges = self.g.es.select(lambda edge: edge["capacity"] >= min and edge["capacity"] <= max)
		print "Found %d edges" % len(subg_edges)
		# find the subgraph restricyed to these edges and vertices connected ot them only
		subg = self.g.subgraph_edges(subg_edges)
		print summary(subg)
		return subg


	def pyqueryroutes(self, first_hop_channel_id, last_hop_channel_remote_pubkey, amount, num_routes):

		# find the pubkey of the node we should start the search from
		# TODO: make that dynamic ><
		own_node_pubkey = "0269b91661812bae52280a68eec2b89d38bf26b33966441ad70aa365e120a125ff"

		if first_hop_channel_id:
			# when -f was specified
			first_hop_id = self.g.es.select(name_eq=(str(first_hop_channel_id)+"_1"))[0].index
			(node1, node2) = self.g.es[first_hop_id].tuple
			if self.g.vs[node1]["name"] == own_node_pubkey:
				node_from_pubkey = self.g.vs[node2]["name"]
			else:
				node_from_pubkey = self.g.vs[node1]["name"]

			self.node_from_pubkey = node_from_pubkey
		else:
			# here no -f paramater was used, any first channel is fair game, so we use our own pubkey as first node
			self.node_from_pubkey = own_node_pubkey


		# modes currently supported: -t, -f/-t. TODO: -f only
		# now we just need to blacklist my own node's direct channels in order not to use that short route :D
		# this is only in -f mode, if no source channel was specified we need to be smarter, see below
		if first_hop_channel_id:
			self.first_hop_capacity = self.g.es.select(name_eq=(str(first_hop_channel_id)+"_1"))[0]["capacity"]
			own_node_pubkey_id = self.g.vs.select(name_eq=own_node_pubkey)[0].index
			self.g.delete_vertices(own_node_pubkey_id)
		else:
			# when -f is not specified, we need to keep all channels going OUT of our node, but remove the
			# ones coming in; we'll use the directionality of the graph for that
			# TODO
			print "No -f mode used, blacklisting all incoming channels"
			own_node_pubkey_id = self.g.vs.select(name_eq=own_node_pubkey)[0].index
			all_incoming_channels = self.g.es.select(_target=own_node_pubkey_id)
			print "Blacklisting %d directional channels" % len(all_incoming_channels)
			self.g.delete_edges(all_incoming_channels)
			print "Also blacklisting the one existing channel we would like to rebalance"
			last_hop_channel_remote_pubkey_id = self.g.vs.select(name_eq=last_hop_channel_remote_pubkey)[0].index
			that_one_channel = self.g.es.select(_source=own_node_pubkey_id, _target=last_hop_channel_remote_pubkey_id)
			self.g.delete_edges(that_one_channel)
			print "Finally, blacklisting all channels which would fail the low local ratio test"
			# TODO

			def get_local_ratio(channel, amount):
			    remote = channel.remote_balance + amount
			    local = channel.local_balance - amount
			    return float(local) / (remote + local)

			# TODO: pass channel_ratio here in order to do that check respecting the CLI parameter
			invalid_local_chans = [c.chan_id for c in 
						list(filter(lambda c: get_local_ratio(c, amount) < 1 - 0.5, self.lnd.get_channels()))]
			print "invalid chans:\n %s" % sorted(invalid_local_chans)
			print "Blacklisting %d channels" % len(invalid_local_chans)
			print "own_node_pubkey: %s" % own_node_pubkey
			own_channels = self.g.es.select(_source=own_node_pubkey_id)
			own_channels_ = [(c.index, c["name"]) for c in own_channels]
			print "still %d own channels " % len(own_channels_)
			print own_channels_
			to_ban = []
			for index, name in own_channels_:
				#raw_input("Checking for %s, %s" % (name, int(name[:-2])))
				if int(name[:-2]) in invalid_local_chans:
					print "Deleting %s" % name
					to_ban.extend([index])
			self.g.delete_edges(to_ban)
			raw_input("ok?")


		print summary(self.g)

		# now we prune the graph by removing useless channels (with a small capacity, currently <3*amount)
		print "Getting subgraph"
		# subgraph parameters are in sats
		self.g = self.subgraph_capacity(self.g, min=3*amount, max=2e20)
		print summary(self.g)

		# 3rd parameter is the amount in sats
		yen = Yen(self.lnd, self.g, amount)

		#yen.display_channel_info("612680864474005505_1")

		#node_from_pubkey = "034a0fa8e6d83688f3e19c2bcb93fb9d6f366d6c937dbc3c744cb21db6e093958b"
		#node_to_pubkey = "02c287d1be9c9fa13d4ded0b0432b7e2367b1b20d822ab76546c4bb67cac1bc6e1"
		node_to_pubkey = last_hop_channel_remote_pubkey
		yen.display_node_info(self.node_from_pubkey)
		yen.display_node_info(node_to_pubkey)

		node_from_id = yen.get_node_id_from_pubkey(self.node_from_pubkey)
		node_to_id = yen.get_node_id_from_pubkey(node_to_pubkey)
		
		# yen_igraph(self, source, target, num_k, weights)
		A, A_costs = yen.yen_igraph(node_from_id, node_to_id, num_routes, None)

		A_chans = []

		for p, c in zip(A, A_costs):
			channels = [self.g.es.select(_source=p[i], _target=p[i+1])[0] for i in range(len(p)-1)]
			A_chans.extend([channels])
			print "Exact cost: %d (estimated %d) - %s - %s" % (c,
															   sum([self.g.es.select(_source=p[i], _target=p[i+1])[0]["weight"]
															   for i in range(len(p)-1)]),
															   p,
															   [c["name"] for c in channels]
															   )
		return A, A_costs, A_chans






