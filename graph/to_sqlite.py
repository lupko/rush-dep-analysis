import os
import sys
import rdflib
import sqlite3
from rdflib import URIRef, Literal

__location__ = os.path.realpath(
    os.path.join(os.getcwd(), os.path.dirname(__file__)))

with open(os.path.join(__location__, 'sqlite.ddl')) as f:
    _DDL = f.read()


def _initialize_store(to_file):
    global _C

    _C = sqlite3.connect(to_file)
    _C.cursor().executescript(_DDL)


def _extract_value_and_type(obj):
    if isinstance(obj, URIRef):
        return '/prefix/'.join(obj.split('/prefix/')[1:]), "entity"
    elif isinstance(obj, Literal):
        return obj, "label"
    else:
        raise ValueError()


_NODE_ID = 1


def _add_node(val_and_type, nodes):
    global _NODE_ID
    value, t = val_and_type

    if value in nodes:
        if t in nodes[value]:
            return nodes[value][t]
        else:
            id = _NODE_ID
            nodes[value][t] = id
            _NODE_ID += 1
            return id
    else:
        nodes[value] = dict()
        id = _NODE_ID
        nodes[value][t] = id
        _NODE_ID += 1
        return id


def _to_node_rows(nodes):
    return [[node_id, value, 1 if node_type is "label" else 0]
            for value, types in nodes.items()
            for node_type, node_id in types.items()
            ]


def create_sqlite_db(from_file, to_file):
    _initialize_store(to_file)

    g = rdflib.ConjunctiveGraph()
    g.parse(from_file, format="turtle", publicID="/prefix/")

    print("number of nodes %d" % (len(g.all_nodes())))

    nodes = dict()
    edges = list()

    for s, p, o, _ in g.quads():
        subject = _extract_value_and_type(s)
        predicate_value, _ = _extract_value_and_type(p)
        obj = _extract_value_and_type(o)

        subject_id = _add_node(subject, nodes)
        obj_id = _add_node(obj, nodes)
        edges.append([subject_id, obj_id, predicate_value])

    cursor = _C.cursor()
    cursor.executemany("INSERT INTO node (id, value, is_label) VALUES (?, ?, ?)", _to_node_rows(nodes))
    cursor.executemany("INSERT INTO edge (from_id, to_id, type) VALUES (?, ?, ?)", edges)
    _C.commit()
    _C.close()


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Specify two arguments: path to file with n-quads and path for sqlite db to create and populate")
        sys.exit(1)
    else:
        to_file = sys.argv[2]

        if os.path.isfile(to_file):
            print("File already exists: %s" % to_file)
            sys.exit(1)

        create_sqlite_db(sys.argv[1], to_file)
