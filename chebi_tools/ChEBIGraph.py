import logging
import obonet
import warnings

import networkx as nx
import pandas as pd

from networkx.exception import NodeNotFound
from pyvis.network import Network
from tqdm import tqdm

from . import ChEBIDownloader


class ChEBIGraph:
    def __init__(self, download_dir=None, G=None):
        self.downloader = ChEBIDownloader(download_dir=download_dir)
        self.requires = ['obo']
        self.downloader.download_missing(self.requires)
        self.download_dir = self.downloader.download_dir
        self.G = G
        if G is None:
            self.load_graph()

        # self.df = self.get_data_from_graph()

    def check_node(self, node):
        data = self.G.nodes[node]
        if "property_value" not in data.keys():
            return False
        formula = self.get_property_from_node(node, "formula")
        mass = self.get_property_from_node(node, "monoisotopicmass")
        if (formula is None) or ("R" in formula) or (formula == ""):
            return False
        if (mass is None) or (mass < 50) or (mass > 1500):
            return False
        return True

    def load_graph(self):
        fn = self.downloader.get_path("obo")
        logging.warning(f"Loading topology from: {fn}")
        self.G = obonet.read_obo(fn)

    def prepare(self):
        self.remove_deuterated_compounds()
        self.remove_oligopeptides()
        self.remove_compound_classes_nodes()
        self.remove_isotopically_modified_compounds()

    def remove_unnecessary_nodes(self):
        warnings.warn(".remove_unnecessary_nodes() is deprecated, use .prepare() instead", DeprecationWarning)

        self.prepare()

    def remove_compound_classes_nodes(self):
        # Remove nodes without propertie values
        logging.warning("Removing compound classes nodes")
        nodes_to_remove = [n for n in tqdm(self.nodes) if not self.check_node(n)]
        self.G.remove_nodes_from(nodes_to_remove)

        ## Remove edges which are not in the list
        edge_types_to_keep = [
            "is_conjugate_acid_of",
            "is_conjugate_base_of",
            "is_enantiomer_of",
            "is_tautomer_of",
            "is_a",
        ]
        edges_to_remove = [
            edge for edge in self.G.edges if edge[2] not in edge_types_to_keep
        ]
        self.G.remove_edges_from(edges_to_remove)

    def remove_deuterated_compounds(self):
        logging.warning("Removing deuterated compounds")
        self.remove_subgraph("CHEBI:76107", undirected=True, reverse_graph=True, depth=1)

    def remove_dipeptides(self):
        logging.warning("Removing dipeptides")
        self.remove_subgraph("CHEBI:46761", undirected=True, reverse_graph=True, depth=1)

    def remove_tripeptides(self):
        logging.warning("Removing tripeptides")
        self.remove_subgraph("CHEBI:47923", undirected=True, reverse_graph=True, depth=1)

    def remove_tetrapeptides(self):
        logging.warning("Removing tetrapeptides")
        self.remove_subgraph("CHEBI:48030", undirected=True, reverse_graph=True, depth=1)

    def remove_pentapeptides(self):
        logging.warning("Removing pentapeptides")
        self.remove_subgraph("CHEBI:48545", undirected=True, reverse_graph=True, depth=1)

    def remove_oligopeptides(self):
        logging.warning("Removing oligopeptides")
        self.remove_dipeptides()
        self.remove_tripeptides()
        self.remove_tetrapeptides()
        self.remove_pentapeptides()
        self.remove_subgraph("CHEBI:25676", undirected=True, reverse_graph=True, depth=1)

    def remove_isotopically_modified_compounds(self):
        logging.warning('Removing isotopically modified compounds')
        self.remove_subgraph('CHEBI:139358', depth=2, undirected=False, reverse_graph=True)


    def remove_subgraph(self, token, depth=1, undirected=False, reverse_graph=False):
        try:
            a = self.get_subgraph(token, depth=depth, undirected=undirected, reverse_graph=reverse_graph)
            self.G.remove_nodes_from(a.nodes)
        except NodeNotFound as e:
            logging.warning(e)

    def get_subgraph(
        self,
        token="CHEBI:25350",
        name=None,
        depth=10,
        undirected=True,
        show=False,
        reverse_graph=False,
        **kwargs,
    ):
        G = self.G
        if reverse_graph:
            G = G.reverse(copy=True)
        H = nx.ego_graph(G, token, depth, undirected=undirected)
        if reverse_graph:
            H = H.reverse(copy=True)
        if show:
            if name is None:
                name = token
            return H, self.show_graph(H, name=name, **kwargs)
        return H

    def show_graph(
        self,
        G,
        name="graph",
        height="800px",
        width="1000px",
        notebook=True,
        directed=True,
        max_nodes=250
    ):

        n_nodes = len(G.nodes)

        if n_nodes > max_nodes:
            logging.warning(f"Too many nodes to plot (n={n_nodes})")
            return None

        fn = f'{"".join([e for e in name if e.isalnum()])}.html'
        for n in G.nodes(data=True):
            n[1]["title"] = n[0]  # add hoovering to graph
            n[1]["label"] = '\n'.join([n[0], n[1]["name"]])  # add hoovering to graph

        nt = Network(height, width, notebook=notebook, directed=directed)
        nt.from_nx(G)
        return nt.show(fn)

    def update_df(self):
        self.df = self.get_data_from_graph()

    def get_data_from_graph(self, props_to_extract=None):
        results = []
        for node in self.G.nodes:
            results.append(
                self.get_data_from_node(node, props_to_extract=props_to_extract)
            )
        return pd.DataFrame.from_records(results).set_index("ChEBI")

    def get_data_from_node(self, token, props_to_extract=None):
        if props_to_extract is None:
            props_to_extract = [
                "monoisotopicmass",
                "charge",
                "formula",
                "inchikey",
                "smiles",
            ]

        data = self.G.nodes[token]

        result = dict(
            ChEBI=token,
            compound_id=int(token.lower().replace("chebi:", "")),
            name=data["name"],
        )

        for prop_name in props_to_extract:
            value = self.get_property_from_node(token, prop_name)
            result.update({prop_name: value})

        return result

    def get_property_from_node(self, token, prop="smiles"):
        node = self.G.nodes[token]
        if "property_value" in node:
            properties = self.G.nodes[token]["property_value"]
        else:
            return None
        value = None
        for string in properties:
            if "/" + prop + " " in string:
                value = string.split('"')[1]
        if value is not None:
            try:
                value = float(value)
            except ValueError:
                pass
        return value

    def get_reference_chebi_of_group(self, group_ids):
        data = self.df.loc[group_ids].copy()
        data["abs_charge"] = data.charge.abs()
        data["name_alpha"] = ~data.name.str.replace(' ', '').str.isalpha()
        data["name_length"] = data.name.apply(len)
        data = data.sort_values(["name_alpha", "name_length"])
        grps = data.groupby(["abs_charge", "name_alpha"])
        for ndx, grp in grps:
            return grp.index[0], grp.name[0]
        return None, None


    
    def get_group(self, name, **kwargs):
        H = self.get_subgraph(name, **kwargs)
        return list(H.nodes)

    @property
    def nodes(self):
        return self.G.nodes

    @property
    def edges(self):
        return self.G.edges
