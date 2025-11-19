import pm4py
from pm4py.visualization.process_tree import visualizer as pt_vis
from pm4py.visualization.petri_net import visualizer as petri_vis

from pm4py.objects.conversion.log import converter as log_converter
from pm4py.algo.filtering.log.attributes import attributes_filter

from pm4py.algo.discovery.dfg.variants import performance as dfg_perf_variant
from pm4py.statistics.start_activities.log import get as get_start_activity
from pm4py.algo.conformance.tokenreplay import algorithm as token_replay


def visualize_process_tree_graphviz(tree, filename="process_tree"):
    gviz = pt_vis.apply(tree)
    pt_vis.save(gviz, f"{filename}.jpg")   
    pt_vis.view(gviz)

def visualize_petri_net_graphviz(net, im, fm, filename="petrinet"):
    gviz = petri_vis.apply(net, im, fm)
    petri_vis.save(gviz, f"{filename}.jpg")
    petri_vis.view(gviz) 

"""
compute frequency according to count of chilrend nodes
"""
def compute_leaf_frequency(log):
    return attributes_filter.get_attribute_values(log, "concept:name")

def compute_frequency_metric(tree, log):
    leaf_freqs = compute_leaf_frequency(log=log)

    if tree is None:
        return {}
    
    freq_map = {}
    def recurse(node):
        # leaf node
        if getattr(node, "label", None) and not getattr(node, "children", []):
            val = leaf_freqs.get(node.label, 0.0)
            freq_map[id(node)] = val
            node.add_id =id(node)
            return val

        # internal node
        child_vals = [recurse(c) for c in getattr(node, "children", [])]
        op = getattr(node.operator, "name", "").lower() if hasattr(node, "operator") else None

        if not child_vals:
            val = 0.0
        elif op == "xor":
            val = sum(child_vals)
        elif op in ("sequence", "parallel"):
            val = max(child_vals)
        elif op == "loop":
            # assume first child is 'do' body
            val = max(child_vals) # count of body usually larger
        else:
            # unknown operator: use average
            val = sum(child_vals) / len(child_vals)

        freq_map[id(node)] = val
        node.add_id = id(node)
        return val
    
    recurse(tree)

    max_val = max(freq_map.values())
    min_val = min(freq_map.values())
    freq_norm = {n: (val-min_val)/(max_val-min_val+1e-9) for n, val in freq_map.items()}
    return freq_norm, tree

"""
dfg edges time interval as waiting time for leaf nodes
tree waiting time according to the children waiting time and split operator
"""
def compute_leaf_waiting_time(log):
    if not hasattr(log, "attributes"):
        log = log_converter.apply(log)

    dfg = dfg_perf_variant.apply(log)

    # edges->performance
    waiting_times = {}
    for (src, tgt), mean_time in dfg.items():
        waiting_times.setdefault(tgt, []).append(mean_time)

    # first actity waiting time set to 0
    start_acts = get_start_activity.get_start_activities(log)
    for act in start_acts:
        if act not in waiting_times:
            waiting_times[act] = [0.0]
    
    avg_wait = {act: sum(vals)/len(vals) for act, vals in waiting_times.items() if vals}
    return avg_wait

def compute_waiting_metric(tree, log):
    leaf_waiting_times = compute_leaf_waiting_time(log=log)
    leaf_freqs = compute_leaf_frequency(log=log)

    if tree is None:
        return {}

    wait_map = {}

    def recurse(node):
        # leaf node
        if getattr(node, "label", None) and not getattr(node, "children", []):
            val = leaf_waiting_times.get(node.label, 0.0)
            wait_map[node.add_id] = val
            return val

        # internal operator
        child_vals = [recurse(c) for c in getattr(node, "children", [])]
        op = getattr(node.operator, "name", "").lower() if hasattr(node, "operator") else None

        if not child_vals:
            val = 0.0

        elif op == "sequence":
            val = sum(child_vals)  # sequential delays add up

        elif op == "xor":
            # weighted average if leaf_freq provided, else simple average
            if leaf_freqs:
                freqs = [leaf_freqs.get(getattr(c, "label", ""), 1.0) for c in node.children]
                total = sum(freqs)
                val = sum(w * f for w, f in zip(child_vals, freqs)) / total if total else sum(child_vals) / len(child_vals)
            else:
                val = sum(child_vals) / len(child_vals)

        elif op == "parallel":
            val = max(child_vals)  # wait for the slowest parallel branch

        elif op == "loop":
            val = child_vals[0] if len(child_vals) > 0 else 0.0

        else:
            val = sum(child_vals) / len(child_vals)

        wait_map[node.add_id] = val
        return val

    recurse(tree)

    max_val = max(wait_map.values())
    min_val = min(wait_map.values())
    wait_norm = {n: (val-min_val)/(max_val-min_val+1e-9) for n, val in wait_map.items()}
    return wait_norm