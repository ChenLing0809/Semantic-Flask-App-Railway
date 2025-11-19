import sys, os
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

import pm4py
from pm4py.objects.process_tree.obj import ProcessTree
from pm4py.objects.conversion.process_tree import converter as pt_converter

from pm4py.visualization.process_tree import visualizer as pt_vis
from pm4py.visualization.petri_net import visualizer as petri_vis
from pm4py.visualization.dfg import visualizer as dfg_vis

from app.utils import visualize_petri_net_graphviz, visualize_process_tree_graphviz
from app.utils import compute_frequency_metric, compute_waiting_metric
#from utils import visualize_petri_net_graphviz, visualize_process_tree_graphviz
import pandas as pd
import math, uuid
import re


MODEL_STORE = {}
AGG_COUNTERS = {"xor": 0, "parallel": 0, "sequence": 0, "loop": 0}

def reset_agg_counters():
    """Reset counters when a new aggregation request happens."""
    for k in AGG_COUNTERS:
        AGG_COUNTERS[k] = 0

def get_max_depth(node, depth=0):
    if not node.children:
        return depth
    
    return max(get_max_depth(c, depth + 1) for c in node.children)

def build_aggregation_label(node):
    op_name = node.operator.name
    child_labels = []
    for c in getattr(node, "children", []):
        if hasattr(c, "label") and c.label:
            child_labels.append(c.label)

    # choose a representative label intelligently
    # improved_label = improve_label(child_labels)

    return f"agg_{op_name}"

def should_aggregate_node(
        node,
        agg_idx,
        agg_till_depth,
        semantic_mode,
        threshold,
        freq_all,
        waiting_all
        ):
    op_name = node.operator.name
    
    # depth_factor to avoid low frequency root nodes aggregated too early
    depth_factor = agg_idx / (agg_till_depth + 1e-9)
    depth_factor = min(depth_factor, 1.0)
    alpha = 0 # define how late to aggregate, default set to 0, no delay effect

    node_id = node.add_id
    if semantic_mode in ("infrequent", "frequent"):
        val_norm = freq_all.get(node_id, None)
    if semantic_mode in ("short_time", "long_time"):
        val_norm = waiting_all.get(node_id, None)

    # when to aggregate node, only consider aggregate block, exclude sequences and parallel in frequence and time situation
    if semantic_mode == "none" or (not val_norm):
        return agg_idx >= agg_till_depth
    
    if ((op_name != "SEQUENCE") and (op_name != "PARALLEL")):
        if semantic_mode in ("infrequent", "short_time"):
            val_new = val_norm * (1 + alpha * (1 - depth_factor))
            return val_new <= threshold or agg_idx >= agg_till_depth
        if semantic_mode in ("frequent", "long_time"):
            val_new = val_norm * (1 - alpha * (1 - depth_factor))
            return val_new > threshold or agg_idx >= agg_till_depth    
    else:
        return False

def hierarchy_aggregation(node, zoom_level, freq_all, waiting_all, semantic_mode, threshold, agg_idx=0, max_depth=None):
    """
    zoom level = 0 -> detailed model, no abstraction
    zoom level = 1 -> most abstract model, only root
    zoom level between 1 and 0, aggregated from deepst till specific depth
    """
    if max_depth is None:
        max_depth = get_max_depth(node)

    agg_till_depth = math.floor((1 - zoom_level) * max_depth)

    if not node.children:
        new_node = ProcessTree(label=node.label)
        return new_node
    
    should_aggregate = False
    should_aggregate = should_aggregate_node(
        node=node,
        agg_idx=agg_idx,
        agg_till_depth=agg_till_depth,
        semantic_mode=semantic_mode,
        threshold=threshold, 
        freq_all=freq_all, 
        waiting_all=waiting_all
    )
    if should_aggregate:
        op_name = getattr(node.operator, "name", "").lower() if node.operator else "unknown"
        if op_name not in AGG_COUNTERS:
            AGG_COUNTERS[op_name] = 0

        AGG_COUNTERS[op_name] += 1
        idx = AGG_COUNTERS[op_name]
        agg_label = f"agg_{op_name}{idx}"
        new_node = ProcessTree(label=agg_label)
        # store the collapsed info
        new_node.aggregated_from = node
        return new_node
    
    new_node = ProcessTree(operator=node.operator)
    for c in node.children:
        child_node = hierarchy_aggregation(c, zoom_level, freq_all, waiting_all, semantic_mode, threshold, agg_idx+1, max_depth)
        child_node.parent = new_node
        new_node.children.append(child_node)

    if node.label:
        new_node.label = node.label

    return new_node


def petri_to_json(net, im, fm):
    nodes, links = [], []

    for p in net.places:
        nodes.append({"id":p.name, "label":p.name, "type":"place"})
    for t in net.transitions:
        label = t.label if t.label else "τ"
        nodes.append({"id":t.name, "label": label, "type":"transition"})
    for arc in net.arcs:
        links.append({"source":arc.source.name, "target":arc.target.name})

    return {"nodes":nodes, "links":links}

def process_tree_to_json(node):
    if node is None:
        return None
    result = {}
    if getattr(node, "label", None):
        result["label"] = node.label
    if getattr(node, "operator", None):
        result["operator"] = node.operator.name.lower() if node.operator else None
    if getattr(node, "children", []):
        result["children"] = [process_tree_to_json(c) for c in node.children]
    if hasattr(node, "aggregated_from"):
        result["aggregated_from"] = process_tree_to_json(node.aggregated_from)
    return result

def discover_process_tree_from_log(file_path):
    if file_path.endswith(".xes"):
        log = pm4py.read_xes(file_path)
    elif file_path.endswith(".csv"):
        df = pd.read_csv(file_path)
        log = pm4py.convert_to_event_log(df)
    else:
        raise ValueError("The uploaded dataformat is not supported!")
    
    tree = pm4py.discover_process_tree_inductive(log)
    net, im, fm = pt_converter.apply(tree)

    # add frequency or waiting aspects
    freq_norm, new_tree = compute_frequency_metric(tree=tree, log=log)
    waiting_norm = compute_waiting_metric(new_tree, log) #TODO

    log_id = str(uuid.uuid4())
    MODEL_STORE[log_id] = {"tree":new_tree, "max_depth": get_max_depth(tree), "frequency":freq_norm, "waiting_time":waiting_norm}
    return log_id, petri_to_json(net, im, fm), process_tree_to_json(tree)

def aggregate_process_tree(log_id, zoom_level, semantic_mode, threshold):
    if log_id not in MODEL_STORE: 
        raise ValueError("Invalid log ID")
    
    tree = MODEL_STORE[log_id]["tree"]
    max_depth = MODEL_STORE[log_id]["max_depth"]
    freq_all = MODEL_STORE[log_id]["frequency"]
    waiting_all = MODEL_STORE[log_id]["waiting_time"]
    agg_tree = hierarchy_aggregation(node=tree, 
                                     zoom_level=zoom_level, 
                                     freq_all=freq_all, 
                                     waiting_all=waiting_all, 
                                     semantic_mode=semantic_mode, 
                                     threshold=threshold, 
                                     max_depth=max_depth)
    agg_net, agg_im, agg_fm = pt_converter.apply(agg_tree)

    return petri_to_json(agg_net, agg_im, agg_fm), process_tree_to_json(agg_tree)
    
if __name__ == "__main__":
    path = ("../uploads/repairExample.xes")
    log_id, petri_json, tree_json = discover_process_tree_from_log(path)
    print("u")
    agg_petri_json, agg_tree_json = aggregate_process_tree(log_id=log_id, zoom_level=0.6, semantic_mode="none", threshold=0.6)

    # visualize original model
    #visualize_process_tree_graphviz(tree, "original_tree")
    #net, im, fm = pt_converter.apply(tree)
    #visualize_petri_net_graphviz(net, im, fm, "orginal_petri")
    
    # get maximal depth of the discovered process tree
    tree = MODEL_STORE[log_id]["tree"]
    max_depth = get_max_depth(tree)
    print("tree_max_depth= ", max_depth)

    for zoom_level in [0.5]:
        agg_tree = hierarchy_aggregation(tree, zoom_level, max_depth=max_depth)
        visualize_process_tree_graphviz(agg_tree, "../test/hier_results/simple labled_agg_tree_zoom level "+str(zoom_level))
        net, im, fm = pt_converter.apply(agg_tree)
        visualize_petri_net_graphviz(net, im, fm, "../test/hier_results/simple labled_agg_petri_zoom level "+str(zoom_level))

        #TODO: improve naming the aggregated nodes, or visualize similar to Paper:Daniel Schuster