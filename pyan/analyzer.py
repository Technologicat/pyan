#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The AST visitor."""

import ast
import logging
import symtable
from typing import Union

from .anutils import (
    ExecuteInInnerScope,
    Scope,
    UnresolvedSuperCallError,
    format_alias,
    get_ast_node_name,
    get_module_name,
    resolve_method_resolution_order,
    canonize_exprs,
    tail,
)
from .node import Flavor, Node

# TODO: add Cython support (strip type annotations in a preprocess step, then treat as Python)
# TODO: built-in functions (range(), enumerate(), zip(), iter(), ...):
#       add to a special scope "built-in" in analyze_scopes() (or ignore altogether)
# TODO: support Node-ifying ListComp et al, List, Tuple
# TODO: make the analyzer smarter (see individual TODOs below)

# Note the use of the term "node" for two different concepts:
#
#  - AST nodes (the "node" argument of CallGraphVisitor.visit_*())
#
#  - The Node class that mainly stores auxiliary information about AST nodes,
#    for the purposes of generating the call graph.
#
#    Namespaces also get a Node (with no associated AST node).

# These tables were useful for porting the visitor to Python 3:
#
# https://docs.python.org/2/library/compiler.html#module-compiler.ast
# https://docs.python.org/3/library/ast.html#abstract-grammar
#


class CallGraphVisitor(ast.NodeVisitor):
    """A visitor that can be walked over a Python AST, and will derive
    information about the objects in the AST and how they use each other.

    A single CallGraphVisitor object can be run over several ASTs (from a
    set of source files).  The resulting information is the aggregate from
    all files.  This way use information between objects in different files
    can be gathered."""

    def __init__(self, filenames, root: str = None, logger=None):
        self.logger = logger or logging.getLogger(__name__)

        # full module names for all given files
        self.module_to_filename = {}  # inverse mapping for recording which file each AST node came from
        for filename in filenames:
            mod_name = get_module_name(filename)
            self.module_to_filename[mod_name] = filename
        self.filenames = filenames
        self.root = root

        # data gathered from analysis
        self.defines_edges = {}
        self.uses_edges = {}
        self.nodes = {}  # Node name: list of Node objects (in possibly different namespaces)
        self.scopes = {}  # fully qualified name of namespace: Scope object

        self.class_base_ast_nodes = {}  # pass 1: class Node: list of AST nodes
        self.class_base_nodes = {}  # pass 2: class Node: list of Node objects (local bases, no recursion)
        self.mro = {}  # pass 2: class Node: list of Node objects in Python's MRO order

        # current context for analysis
        self.module_name = None
        self.filename = None
        self.name_stack = []  # for building namespace name, node naming
        self.scope_stack = []  # the Scope objects currently in scope
        self.class_stack = []  # Nodes for class definitions currently in scope
        self.context_stack = []  # for detecting which FunctionDefs are methods

        # Analyze.
        self.process()

    def process(self):
        """Analyze the set of files, twice so that any forward-references are picked up."""
        for pas in range(2):
            for filename in self.filenames:
                self.logger.info("========== pass %d, file '%s' ==========" % (pas + 1, filename))
                self.process_one(filename)
            if pas == 0:
                self.resolve_base_classes()  # must be done only after all files seen
        self.postprocess()

    def process_one(self, filename):
        """Analyze the specified Python source file."""
        if filename not in self.filenames:
            raise ValueError(
                "Filename '%s' has not been preprocessed (was not given to __init__, which got %s)"
                % (filename, self.filenames)
            )
        with open(filename, "rt", encoding="utf-8") as f:
            content = f.read()
        self.filename = filename
        self.module_name = get_module_name(filename, root=self.root)
        self.analyze_scopes(content, filename)  # add to the currently known scopes
        self.visit(ast.parse(content, filename))
        self.module_name = None
        self.filename = None

    def resolve_base_classes(self):
        """Resolve base classes from AST nodes to Nodes.

        Run this between pass 1 and pass 2 to pick up inherited methods.
        Currently, this can parse ast.Names and ast.Attributes as bases.
        """
        self.logger.debug("Resolving base classes")
        assert len(self.scope_stack) == 0  # only allowed between passes
        for node in self.class_base_ast_nodes:  # Node: list of AST nodes
            self.class_base_nodes[node] = []
            for ast_node in self.class_base_ast_nodes[node]:
                # perform the lookup in the scope enclosing the class definition
                self.scope_stack.append(self.scopes[node.namespace])

                if isinstance(ast_node, ast.Name):
                    baseclass_node = self.get_value(ast_node.id)
                elif isinstance(ast_node, ast.Attribute):
                    _, baseclass_node = self.get_attribute(ast_node)  # don't care about obj, just grab attr
                else:  # give up
                    baseclass_node = None

                self.scope_stack.pop()

                if isinstance(baseclass_node, Node) and baseclass_node.namespace is not None:
                    self.class_base_nodes[node].append(baseclass_node)

        self.logger.debug("All base classes (non-recursive, local level only): %s" % self.class_base_nodes)

        self.logger.debug("Resolving method resolution order (MRO) for all analyzed classes")
        self.mro = resolve_method_resolution_order(self.class_base_nodes, self.logger)
        self.logger.debug("Method resolution order (MRO) for all analyzed classes: %s" % self.mro)

    def postprocess(self):
        """Finalize the analysis."""

        # Compared to the original Pyan, the ordering of expand_unknowns() and
        # contract_nonexistents() has been switched.
        #
        # It seems the original idea was to first convert any unresolved, but
        # specific, references to the form *.name, and then expand those to see
        # if they match anything else. However, this approach has the potential
        # to produce a lot of spurious uses edges (for unrelated functions with
        # a name that happens to match).
        #
        # Now that the analyzer is (very slightly) smarter about resolving
        # attributes and imports, we do it the other way around: we only expand
        # those references that could not be resolved to any known name, and
        # then remove any references pointing outside the analyzed file set.

        self.expand_unknowns()
        self.resolve_imports()
        self.contract_nonexistents()
        self.cull_inherited()
        self.collapse_inner()

    ###########################################################################
    # visitor methods

    # In visit_*(), the "node" argument refers to an AST node.

    # Python docs:
    # https://docs.python.org/3/library/ast.html#abstract-grammar

    def resolve_imports(self):
        """
        resolve relative imports and remap nodes
        """
        # first find all imports and map to themselves. we will then remap those that are currently pointing
        # to duplicates or into the void
        imports_to_resolve = {n for items in self.nodes.values() for n in items if n.flavor == Flavor.IMPORTEDITEM}
        # map real definitions
        import_mapping = {}
        while len(imports_to_resolve) > 0:
            from_node = imports_to_resolve.pop()
            if from_node in import_mapping:
                continue
            to_uses = self.uses_edges.get(from_node, set([from_node]))
            assert len(to_uses) == 1
            to_node = to_uses.pop()  # resolve alias
            # resolve namespace and get module
            if to_node.namespace == "":
                module_node = to_node
            else:
                assert from_node.name == to_node.name
                module_node = self.get_node("", to_node.namespace)
            module_uses = self.uses_edges.get(module_node)
            if module_uses is not None:
                # check if in module item exists and if yes, map to it
                for candidate_to_node in module_uses:
                    if candidate_to_node.name == from_node.name:
                        to_node = candidate_to_node
                        import_mapping[from_node] = to_node
                        if to_node.flavor == Flavor.IMPORTEDITEM and from_node is not to_node:  # avoid self-recursion
                            imports_to_resolve.add(to_node)
                        break

        # set previously undefined nodes to defined
        # go through undefined attributes
        attribute_import_mapping = {}
        for nodes in self.nodes.values():
            for node in nodes:
                if not node.defined and node.flavor == Flavor.ATTRIBUTE:
                    # try to resolve namespace and find imported item mapping
                    for from_node, to_node in import_mapping.items():
                        if (
                            f"{from_node.namespace}.{from_node.name}" == node.namespace
                            and from_node.flavor == Flavor.IMPORTEDITEM
                        ):
                            # use define edges as potential candidates
                            for candidate_to_node in self.defines_edges[to_node]:  #
                                if candidate_to_node.name == node.name:
                                    attribute_import_mapping[node] = candidate_to_node
                                    break
        import_mapping.update(attribute_import_mapping)

        # remap nodes based on import mapping
        self.nodes = {name: [import_mapping.get(n, n) for n in items] for name, items in self.nodes.items()}
        self.uses_edges = {
            import_mapping.get(from_node, from_node): {import_mapping.get(to_node, to_node) for to_node in to_nodes}
            for from_node, to_nodes in self.uses_edges.items()
            if len(to_nodes) > 0
        }
        self.defines_edges = {
            import_mapping.get(from_node, from_node): {import_mapping.get(to_node, to_node) for to_node in to_nodes}
            for from_node, to_nodes in self.defines_edges.items()
            if len(to_nodes) > 0
        }

    def filter(self, node: Union[None, Node] = None, namespace: Union[str, None] = None, max_iter: int = 1000):
        """
        filter callgraph nodes that related to `node` or are in `namespace`

        Args:
            node: pyan node for which related nodes should be found, if none, filter only for namespace
            namespace: namespace to search in (name of top level module),
                if None, determines namespace from `node`
            max_iter: maximum number of iterations and nodes to iterate

        Returns:
            self
        """
        # filter the nodes to avoid cluttering the callgraph with irrelevant information
        filtered_nodes = self.get_related_nodes(node, namespace=namespace, max_iter=max_iter)

        self.nodes = {name: [node for node in nodes if node in filtered_nodes] for name, nodes in self.nodes.items()}
        self.uses_edges = {
            node: {n for n in nodes if n in filtered_nodes}
            for node, nodes in self.uses_edges.items()
            if node in filtered_nodes
        }
        self.defines_edges = {
            node: {n for n in nodes if n in filtered_nodes}
            for node, nodes in self.defines_edges.items()
            if node in filtered_nodes
        }
        return self

    def get_related_nodes(
        self, node: Union[None, Node] = None, namespace: Union[str, None] = None, max_iter: int = 1000
    ) -> set:
        """
        get nodes that related to `node` or are in `namespace`

        Args:
            node: pyan node for which related nodes should be found, if none, filter only for namespace
            namespace: namespace to search in (name of top level module),
                if None, determines namespace from `node`
            max_iter: maximum number of iterations and nodes to iterate

        Returns:
            set: set of nodes related to `node` including `node` itself
        """
        # check if searching through all nodes is necessary
        if node is None:
            queue = []
            if namespace is None:
                new_nodes = {n for items in self.nodes.values() for n in items}
            else:
                new_nodes = {
                    n
                    for items in self.nodes.values()
                    for n in items
                    if n.namespace is not None and namespace in n.namespace
                }

        else:
            new_nodes = set()
            if namespace is None:
                namespace = node.namespace.strip(".").split(".", 1)[0]
            queue = [node]

        # use queue system to search through nodes
        # essentially add a node to the queue and then search all connected nodes which are in turn added to the queue
        # until the queue itself is empty or the maximum limit of max_iter searches have been hit
        i = max_iter
        while len(queue) > 0:
            item = queue.pop()
            if item not in new_nodes:
                new_nodes.add(item)
                i -= 1
                if i < 0:
                    break
                queue.extend(
                    [
                        n
                        for n in self.uses_edges.get(item, [])
                        if n in self.uses_edges and n not in new_nodes and namespace in n.namespace
                    ]
                )
                queue.extend(
                    [
                        n
                        for n in self.defines_edges.get(item, [])
                        if n in self.defines_edges and n not in new_nodes and namespace in n.namespace
                    ]
                )

        return new_nodes

    def visit_Module(self, node):
        self.logger.debug("Module %s, %s" % (self.module_name, self.filename))

        # Modules live in the top-level namespace, ''.
        module_node = self.get_node("", self.module_name, node, flavor=Flavor.MODULE)
        self.associate_node(module_node, node, filename=self.filename)

        ns = self.module_name
        self.name_stack.append(ns)
        self.scope_stack.append(self.scopes[ns])
        self.context_stack.append("Module %s" % (ns))
        self.generic_visit(node)  # visit the **children** of node
        self.context_stack.pop()
        self.scope_stack.pop()
        self.name_stack.pop()

        if self.add_defines_edge(module_node, None):
            self.logger.info("Def Module %s" % node)

    def visit_ClassDef(self, node):
        self.logger.debug("ClassDef %s, %s:%s" % (node.name, self.filename, node.lineno))

        from_node = self.get_node_of_current_namespace()
        ns = from_node.get_name()
        to_node = self.get_node(ns, node.name, node, flavor=Flavor.CLASS)
        if self.add_defines_edge(from_node, to_node):
            self.logger.info("Def from %s to Class %s" % (from_node, to_node))

        # The graph Node may have been created earlier by a FromImport,
        # in which case its AST node points to the site of the import.
        #
        # Change the AST node association of the relevant graph Node
        # to this AST node (the definition site) to get the correct
        # source line number information in annotated output.
        #
        self.associate_node(to_node, node, self.filename)

        # Bind the name specified by the AST node to the graph Node
        # in the current scope.
        #
        self.set_value(node.name, to_node)

        self.class_stack.append(to_node)
        self.name_stack.append(node.name)
        inner_ns = self.get_node_of_current_namespace().get_name()
        self.scope_stack.append(self.scopes[inner_ns])
        self.context_stack.append("ClassDef %s" % (node.name))

        self.class_base_ast_nodes[to_node] = []
        for b in node.bases:
            # gather info for resolution of inherited attributes in pass 2 (see get_attribute())
            self.class_base_ast_nodes[to_node].append(b)
            # mark uses from a derived class to its bases (via names appearing in a load context).
            self.visit(b)

        for stmt in node.body:
            self.visit(stmt)

        self.context_stack.pop()
        self.scope_stack.pop()
        self.name_stack.pop()
        self.class_stack.pop()

    def visit_FunctionDef(self, node):
        self.logger.debug("FunctionDef %s, %s:%s" % (node.name, self.filename, node.lineno))

        # To begin with:
        #
        # - Analyze decorators. They belong to the surrounding scope,
        #   so we must analyze them before entering the function scope.
        #
        # - Determine whether this definition is for a function, an (instance)
        #   method, a static method or a class method.
        #
        # - Grab the name representing "self", if this is either an instance
        #   method or a class method. (For a class method, it represents cls,
        #   but Pyan only cares about types, not instances.)
        #
        self_name, flavor = self.analyze_functiondef(node)

        # Now we can create the Node.
        #
        from_node = self.get_node_of_current_namespace()
        ns = from_node.get_name()
        to_node = self.get_node(ns, node.name, node, flavor=flavor)
        if self.add_defines_edge(from_node, to_node):
            self.logger.info("Def from %s to Function %s" % (from_node, to_node))

        # Same remarks as for ClassDef above.
        #
        self.associate_node(to_node, node, self.filename)
        self.set_value(node.name, to_node)

        # Enter the function scope
        #
        self.name_stack.append(node.name)
        inner_ns = self.get_node_of_current_namespace().get_name()
        self.scope_stack.append(self.scopes[inner_ns])
        self.context_stack.append("FunctionDef %s" % (node.name))

        # Capture which names correspond to function args.
        #
        self.generate_args_nodes(node.args, inner_ns)

        # self_name is just an ordinary name in the method namespace, except
        # that its value is implicitly set by Python when the method is called.
        #
        # Bind self_name in the function namespace to its initial value,
        # i.e. the current class. (Class, because Pyan cares only about
        # object types, not instances.)
        #
        # After this point, self_name behaves like any other name.
        #
        if self_name is not None:
            class_node = self.get_current_class()
            self.scopes[inner_ns].defs[self_name] = class_node
            self.logger.info('Method def: setting self name "%s" to %s' % (self_name, class_node))

        # record bindings of args to the given default values, if present
        self.analyze_arguments(node.args)

        # Visit type annotations to create uses edges for referenced types.
        if node.returns is not None:
            self.visit(node.returns)
        for arg in node.args.args + node.args.posonlyargs + node.args.kwonlyargs:
            if arg.annotation is not None:
                self.visit(arg.annotation)
        if node.args.vararg is not None and node.args.vararg.annotation is not None:
            self.visit(node.args.vararg.annotation)
        if node.args.kwarg is not None and node.args.kwarg.annotation is not None:
            self.visit(node.args.kwarg.annotation)

        # Analyze the function body
        #
        for stmt in node.body:
            self.visit(stmt)

        # Exit the function scope
        #
        self.context_stack.pop()
        self.scope_stack.pop()
        self.name_stack.pop()

    def visit_AsyncFunctionDef(self, node):
        self.visit_FunctionDef(node)  # TODO: alias for now; tag async functions in output in a future version?

    def visit_Lambda(self, node):
        # TODO: avoid lumping together all lambdas in the same namespace.
        self.logger.debug("Lambda, %s:%s" % (self.filename, node.lineno))
        with ExecuteInInnerScope(self, "lambda") as scope_ctx:
            self.generate_args_nodes(node.args, scope_ctx.inner_ns)
            self.analyze_arguments(node.args)
            self.visit(node.body)  # single expr
        return scope_ctx.inner_scope_node

    def generate_args_nodes(self, ast_args, inner_ns):
        """Capture which names correspond to function args.

        In the function scope, set them to a nonsense Node,
        to prevent leakage of identifiers of matching name
        from the enclosing scope (due to the local value being None
        until we set it to this nonsense Node).

        ast_args: node.args from a FunctionDef or Lambda
        inner_ns: namespace of the function or lambda, for scope lookup
        """
        sc = self.scopes[inner_ns]
        # As the name of the nonsense node, we can use any string that
        # is not a valid Python identifier.
        #
        # It has no sensible flavor, so we leave its flavor unspecified.
        nonsense_node = self.get_node(inner_ns, "^^^argument^^^", None)
        # args, vararg (*args), kwonlyargs, kwarg (**kwargs)
        for a in ast_args.args:  # positional
            sc.defs[a.arg] = nonsense_node
        if ast_args.vararg is not None:  # *args if present
            sc.defs[ast_args.vararg] = nonsense_node
        for a in ast_args.kwonlyargs:  # any after *args or *
            sc.defs[a.arg] = nonsense_node
        if ast_args.kwarg is not None:  # **kwargs if present
            sc.defs[ast_args.kwarg] = nonsense_node

    def analyze_arguments(self, ast_args):
        """Analyze an arguments node of the AST.

        Record bindings of args to the given default values, if present.

        Used for analyzing FunctionDefs and Lambdas."""
        # https://greentreesnakes.readthedocs.io/en/latest/nodes.html?highlight=functiondef#arguments
        if ast_args.defaults:
            n = len(ast_args.defaults)
            for tgt, val in zip(ast_args.args[-n:], ast_args.defaults):
                targets = canonize_exprs(tgt)
                values = canonize_exprs(val)
                self.analyze_binding(targets, values)
        if ast_args.kw_defaults:
            n = len(ast_args.kw_defaults)
            for tgt, val in zip(ast_args.kwonlyargs, ast_args.kw_defaults):
                if val is not None:
                    targets = canonize_exprs(tgt)
                    values = canonize_exprs(val)
                    self.analyze_binding(targets, values)

    def visit_Import(self, node):
        self.logger.debug("Import %s, %s:%s" % ([format_alias(x) for x in node.names], self.filename, node.lineno))

        # TODO: add support for relative imports (path may be like "....something.something")
        # https://www.python.org/dev/peps/pep-0328/#id10

        for import_item in node.names:  # the names are modules
            self.analyze_module_import(import_item, node)

    def visit_ImportFrom(self, node):
        self.logger.debug(
            "ImportFrom: from %s import %s, %s:%s"
            % (node.module, [format_alias(x) for x in node.names], self.filename, node.lineno)
        )
        # Pyan needs to know the package structure, and how the program
        # being analyzed is actually going to be invoked (!), to be able to
        # resolve relative imports correctly.
        #
        # As a solution, we register imports here and later, when all files have been parsed, resolve them.
        from_node = self.get_node_of_current_namespace()
        if node.module is None:  # resolve relative imports 'None' such as "from . import foo"
            self.logger.debug(
                "ImportFrom (original) from %s import %s, %s:%s"
                % ("." * node.level, [format_alias(x) for x in node.names], self.filename, node.lineno)
            )
            tgt_level = node.level
            current_module_namespace = self.module_name.rsplit(".", tgt_level)[0]
            tgt_name = current_module_namespace
            self.logger.debug(
                "ImportFrom (resolved): from %s import %s, %s:%s"
                % (tgt_name, [format_alias(x) for x in node.names], self.filename, node.lineno)
            )
        elif node.level != 0:  # resolve from ..module import foo
            self.logger.debug(
                "ImportFrom (original): from %s import %s, %s:%s"
                % (node.module, [format_alias(x) for x in node.names], self.filename, node.lineno)
            )
            tgt_level = node.level
            current_module_namespace = self.module_name.rsplit(".", tgt_level)[0]
            tgt_name = current_module_namespace + "." + node.module
            self.logger.debug(
                "ImportFrom (resolved): from %s import %s, %s:%s"
                % (tgt_name, [format_alias(x) for x in node.names], self.filename, node.lineno)
            )
        else:
            tgt_name = node.module  # normal from module.submodule import foo

        # link each import separately
        for alias in node.names:
            # check if import is module
            if tgt_name + "." + alias.name in self.module_to_filename:
                to_node = self.get_node("", tgt_name + "." + alias.name, node, flavor=Flavor.MODULE)
            else:
                to_node = self.get_node(tgt_name, alias.name, node, flavor=Flavor.IMPORTEDITEM)
            # if there is alias, add extra edge between alias and node
            if alias.asname is not None:
                alias_name = alias.asname
            else:
                alias_name = alias.name
            self.set_value(alias_name, to_node)  # set node to be discoverable in module
            self.logger.info("From setting name %s to %s" % (alias_name, to_node))

            self.logger.debug("Use from %s to ImportFrom %s" % (from_node, to_node))
            if self.add_uses_edge(from_node, to_node):
                self.logger.info("New edge added for Use from %s to ImportFrom %s" % (from_node, to_node))

    def analyze_module_import(self, import_item, ast_node):
        """Analyze a names AST node inside an Import or ImportFrom AST node.

        This handles the case where the objects being imported are modules.

        import_item: an item of ast_node.names
        ast_node: for recording source location information
        """
        src_name = import_item.name  # what is being imported

        # mark the use site
        #
        # where it is being imported to, i.e. the **user**
        from_node = self.get_node_of_current_namespace()
        # the thing **being used** (under the asname, if any)
        mod_node = self.get_node("", src_name, ast_node, flavor=Flavor.MODULE)
        # if there is alias, add extra edge between alias and node
        if import_item.asname is not None:
            alias_name = import_item.asname
        else:
            alias_name = mod_node.name
        self.add_uses_edge(from_node, mod_node)
        self.logger.info("New edge added for Use import %s in %s" % (mod_node, from_node))
        self.set_value(alias_name, mod_node)  # set node to be discoverable in module
        self.logger.info("From setting name %s to %s" % (alias_name, mod_node))

    # Edmund Horner's original post has info on what this fixed in Python 2.
    # https://ejrh.wordpress.com/2012/01/31/call-graphs-in-python-part-2/
    #
    # Essentially, this should make '.'.join(...) see str.join.
    # Pyan3 currently handles that in resolve_attribute() and get_attribute().
    #
    # Python 3.4 does not have ast.Constant, but 3.6 does.
    # TODO: actually test this with Python 3.6 or later.
    #
    def visit_Constant(self, node):
        self.logger.debug("Constant %s, %s:%s" % (node.value, self.filename, node.lineno))
        t = type(node.value)
        ns = self.get_node_of_current_namespace().get_name()
        tn = t.__name__
        return self.get_node(ns, tn, node, flavor=Flavor.ATTRIBUTE)

    # attribute access (node.ctx is ast.Load/Store/Del)
    # Store context: handled by _bind_target
    # Del context: handled by visit_Delete (protocol method edges)
    def visit_Attribute(self, node):
        objname = get_ast_node_name(node.value)
        self.logger.debug(
            "Attribute %s of %s in context %s, %s:%s" % (node.attr, objname, type(node.ctx), self.filename, node.lineno)
        )

        if isinstance(node.ctx, ast.Load):
            try:
                obj_node, attr_node = self.get_attribute(node)
            except UnresolvedSuperCallError:
                # Avoid adding a wildcard if the lookup failed due to an
                # unresolved super() in the attribute chain.
                return

            # Both object and attr known.
            if isinstance(attr_node, Node):
                self.logger.info("getattr %s on %s returns %s" % (node.attr, objname, attr_node))

                # add uses edge
                from_node = self.get_node_of_current_namespace()
                self.logger.debug("Use from %s to %s" % (from_node, attr_node))
                if self.add_uses_edge(from_node, attr_node):
                    self.logger.info("New edge added for Use from %s to %s" % (from_node, attr_node))

                # remove resolved wildcard from current site to <Node *.attr>
                if attr_node.namespace is not None:
                    self.remove_wild(from_node, attr_node, node.attr)

                return attr_node

            # Object known, but attr unknown. Create node and add a uses edge.
            #
            # TODO: this is mainly useful for imports. Should probably disallow
            # creating new attribute nodes for other undefined attrs of known objs.
            #
            # E.g.
            #
            # import math  # create <Node math>
            # math.sin     # create <Node math.sin> (instead of <Node *.sin> even though math.py is not analyzed)
            #
            # This sometimes creates silly nodes such as (when analyzing Pyan itself)
            # <Node pyan.analyzer.CallGraphVisitor.defines_edges.name.namespace>
            # but these are harmless, as they are considered undefined and
            # will not be visualized.
            #
            elif isinstance(obj_node, Node) and obj_node.namespace is not None:
                tgt_name = node.attr
                from_node = self.get_node_of_current_namespace()
                ns = obj_node.get_name()  # fully qualified namespace **of attr**
                to_node = self.get_node(ns, tgt_name, node, flavor=Flavor.ATTRIBUTE)
                self.logger.debug(
                    f"Use from {from_node} to {to_node} (target obj {obj_node} known but target attr "
                    f"{node.attr} not resolved; maybe fwd ref or unanalyzed import)"
                )
                if self.add_uses_edge(from_node, to_node):
                    self.logger.info(
                        "New edge added for Use from {from_node} to {to_node} (target obj {obj_node} known but "
                        f"target attr {node.attr} not resolved; maybe fwd ref or unanalyzed import)"
                    )

                # remove resolved wildcard from current site to <Node *.attr>
                self.remove_wild(from_node, obj_node, node.attr)

                return to_node

            # pass on
            else:
                return self.visit(node.value)
        # Store context: handled by _bind_target
        # Del context: handled by visit_Delete (protocol method edges)

    # name access (node.ctx is ast.Load/Store/Del)
    # Store context: handled by _bind_target
    # Del context: handled by visit_Delete (protocol method edges)
    def visit_Name(self, node):
        self.logger.debug("Name %s in context %s, %s:%s" % (node.id, type(node.ctx), self.filename, node.lineno))

        if isinstance(node.ctx, ast.Load):
            tgt_name = node.id
            to_node = self.get_value(tgt_name)  # resolves "self" if needed
            current_class = self.get_current_class()
            if current_class is None or to_node is not current_class:  # add uses edge only if not pointing to "self"
                if not isinstance(to_node, Node):
                    # Local with no resolved value — no useful type info, skip.
                    if tgt_name in self.scope_stack[-1].locals:
                        return None
                    # namespace=None means we don't know the namespace yet
                    to_node = self.get_node(None, tgt_name, node, flavor=Flavor.UNKNOWN)

                from_node = self.get_node_of_current_namespace()
                self.logger.debug("Use from %s to Name %s" % (from_node, to_node))
                if self.add_uses_edge(from_node, to_node):
                    self.logger.info("New edge added for Use from %s to Name %s" % (from_node, to_node))

            return to_node
        # Store context: handled by _bind_target
        # Del context: handled by visit_Delete (protocol method edges)

    def visit_Assign(self, node):
        # - chaining assignments like "a = b = c" produces multiple targets
        # - tuple unpacking works as a separate mechanism on top of that (see analyze_binding())
        #
        if len(node.targets) > 1:
            self.logger.debug("Assign (chained with %d outputs)" % (len(node.targets)))

        # TODO: support lists, dicts, sets (so that we can recognize calls to their methods)
        # TODO: begin with supporting empty lists, dicts, sets
        # TODO: need to be more careful in sanitizing; currently destroys a bare list

        values = canonize_exprs(node.value)  # values is the same for each set of targets
        for targets in node.targets:
            targets = canonize_exprs(targets)
            self.logger.debug(
                "Assign %s %s, %s:%s"
                % (
                    [get_ast_node_name(x) for x in targets],
                    [get_ast_node_name(x) for x in values],
                    self.filename,
                    node.lineno,
                )
            )
            self.analyze_binding(targets, values)

    def visit_AnnAssign(self, node):  # PEP 526, Python 3.6+
        if node.value is not None:
            targets = canonize_exprs(node.target)
            values = canonize_exprs(node.value)
            # issue #62: value may be an empty list, so it doesn't always have any elements
            # even after `canonize_exprs`.
            self.logger.debug(
                "AnnAssign %s %s, %s:%s"
                % (get_ast_node_name(node.target), get_ast_node_name(node.value), self.filename, node.lineno)
            )
            self.analyze_binding(targets, values)
        else:  # just a type declaration
            self.logger.debug(
                "AnnAssign %s <no value>, %s:%s" % (get_ast_node_name(node.target), self.filename, node.lineno)
            )
            self._bind_target(node.target, None)
        # Visit the type annotation to create uses edges for referenced types.
        if node.annotation is not None:
            self.visit(node.annotation)

    def visit_NamedExpr(self, node):  # PEP 572, Python 3.8+  (walrus operator :=)
        self.logger.debug(
            "NamedExpr %s, %s:%s" % (get_ast_node_name(node.target), self.filename, node.lineno)
        )
        targets = canonize_exprs(node.target)
        values = canonize_exprs(node.value)
        self.analyze_binding(targets, values)
        # Unlike plain assignment, walrus is an *expression* — the enclosing
        # context needs the bound value.
        return self.get_value(node.target.id)

    def visit_TypeAlias(self, node):  # PEP 695, Python 3.12+
        self.logger.debug("TypeAlias %s, %s:%s" % (node.name.id, self.filename, node.lineno))

        # Create defines edge for the alias name.
        from_node = self.get_node_of_current_namespace()
        ns = from_node.get_name()
        to_node = self.get_node(ns, node.name.id, node, flavor=Flavor.NAME)
        if self.add_defines_edge(from_node, to_node):
            self.logger.info("Def from %s to TypeAlias %s" % (from_node, to_node))
        self.associate_node(to_node, node, self.filename)
        self.set_value(node.name.id, to_node)

        # Visit the type value inside its scope. Parameterized aliases have
        # two nested scopes (type parameter scope → type alias scope); simple
        # aliases have just one (type alias scope). CPython's symtable names
        # both scopes after the alias (e.g. "Matrix" and "Matrix.Matrix"),
        # hence the repeated name in ExecuteInInnerScope calls.
        if node.type_params:
            with ExecuteInInnerScope(self, node.name.id):  # type parameter scope
                with ExecuteInInnerScope(self, node.name.id):  # type alias scope
                    self.visit(node.value)
        else:
            with ExecuteInInnerScope(self, node.name.id):
                self.visit(node.value)

    def visit_AugAssign(self, node):
        targets = canonize_exprs(node.target)
        values = canonize_exprs(node.value)  # values is the same for each set of targets

        self.logger.debug(
            "AugAssign %s %s %s, %s:%s"
            % (
                [get_ast_node_name(x) for x in targets],
                type(node.op),
                [get_ast_node_name(x) for x in values],
                self.filename,
                node.lineno,
            )
        )

        # TODO: maybe no need to handle tuple unpacking in AugAssign? (but simpler to use the same implementation)
        self.analyze_binding(targets, values)

    # for() is also a binding form.
    #
    # (Without analyzing the bindings, we would get an unknown node for any
    #  use of the loop counter(s) in the loop body. This would have confusing
    #  consequences in the expand_unknowns() step, if the same name is
    #  in use elsewhere.)
    #
    def _add_iterator_protocol_edges(self, iter_node, is_async=False):
        """Add uses edges for the iterator protocol on `iter_node`.

        Sync iteration:  ``__iter__`` + ``__next__``
        Async iteration: ``__aiter__`` + ``__anext__``
        """
        if isinstance(iter_node, Node):
            from_node = self.get_node_of_current_namespace()
            if is_async:
                methods = ("__aiter__", "__anext__")
            else:
                methods = ("__iter__", "__next__")
            for methodname in methods:
                to_node = self.get_node(iter_node.get_name(), methodname, None, flavor=Flavor.METHOD)
                self.logger.debug("Use from %s to %s (iteration)" % (from_node, to_node))
                if self.add_uses_edge(from_node, to_node):
                    self.logger.info("New edge added for Use from %s to %s (iteration)" % (from_node, to_node))

    def visit_For(self, node):
        self.logger.debug("For-loop, %s:%s" % (self.filename, node.lineno))

        # Visit the iterable to resolve the object node, then add protocol edges.
        # NOTE: node.iter is visited again inside analyze_binding(); the double
        # visit is harmless (resolves to the same node, edges deduplicate).
        iter_node = self.visit(node.iter)
        self._add_iterator_protocol_edges(iter_node)

        targets = canonize_exprs(node.target)
        values = canonize_exprs(node.iter)
        self.analyze_binding(targets, values)

        for stmt in node.body:
            self.visit(stmt)
        for stmt in node.orelse:
            self.visit(stmt)

    def visit_AsyncFor(self, node):
        self.logger.debug("AsyncFor-loop, %s:%s" % (self.filename, node.lineno))

        # NOTE: node.iter is visited again inside analyze_binding(); the double
        # visit is harmless (resolves to the same node, edges deduplicate).
        iter_node = self.visit(node.iter)
        self._add_iterator_protocol_edges(iter_node, is_async=True)

        targets = canonize_exprs(node.target)
        values = canonize_exprs(node.iter)
        self.analyze_binding(targets, values)

        for stmt in node.body:
            self.visit(stmt)
        for stmt in node.orelse:
            self.visit(stmt)

    def visit_ListComp(self, node):
        self.logger.debug("ListComp, %s:%s" % (self.filename, node.lineno))
        return self.analyze_comprehension(node, "listcomp")

    def visit_SetComp(self, node):
        self.logger.debug("SetComp, %s:%s" % (self.filename, node.lineno))
        return self.analyze_comprehension(node, "setcomp")

    def visit_DictComp(self, node):
        self.logger.debug("DictComp, %s:%s" % (self.filename, node.lineno))
        return self.analyze_comprehension(node, "dictcomp", field1="key", field2="value")

    def visit_GeneratorExp(self, node):
        self.logger.debug("GeneratorExp, %s:%s" % (self.filename, node.lineno))
        return self.analyze_comprehension(node, "genexpr")

    def analyze_comprehension(self, node, label, field1="elt", field2=None):
        """Analyze a comprehension node (listcomp, setcomp, dictcomp, genexpr).

        field1 and field2 name the AST attributes holding the output expression(s):
        ListComp/SetComp/GeneratorExp use ``elt``; DictComp uses ``key`` and ``value``.

        Returns the inner scope Node representing the comprehension, so that
        callers (e.g. ``analyze_binding``) can bind it to a target.
        """
        # The outermost iterator is evaluated in the current scope;
        # everything else in the new inner scope.
        #
        # See function symtable_handle_comprehension() in
        #   https://github.com/python/cpython/blob/master/Python/symtable.c
        # For how it works, see
        #   https://stackoverflow.com/questions/48753060/what-are-these-extra-symbols-in-a-comprehensions-symtable
        # For related discussion, see
        #   https://bugs.python.org/issue10544
        gens = node.generators  # tuple of ast.comprehension
        outermost = gens[0]
        moregens = gens[1:] if len(gens) > 1 else []

        outermost_iters = canonize_exprs(outermost.iter)
        outermost_targets = canonize_exprs(outermost.target)
        # Evaluate outermost iterator in current scope.
        iter_node = None
        for expr in outermost_iters:
            iter_node = self.visit(expr)
        self._add_iterator_protocol_edges(iter_node, is_async=outermost.is_async)

        # Ensure comprehension scope exists. On Python 3.12+ (PEP 709),
        # symtable no longer reports listcomp/setcomp/dictcomp as child scopes.
        # Create a synthetic scope with the iteration target names to preserve
        # variable isolation during analysis.
        parent_ns = self.get_node_of_current_namespace().get_name()
        inner_ns = "%s.%s" % (parent_ns, label)
        if inner_ns not in self.scopes:
            target_names = set()
            for gen in gens:
                self._collect_target_names(gen.target, target_names)
            self.scopes[inner_ns] = Scope.from_names(label, target_names)

        with ExecuteInInnerScope(self, label) as scope_ctx:
            # Bind outermost targets to the iterator value in inner scope.
            for tgt in outermost_targets:
                self._bind_target(tgt, iter_node)
            for expr in outermost.ifs:
                self.visit(expr)

            for gen in moregens:
                targets = canonize_exprs(gen.target)
                values = canonize_exprs(gen.iter)
                self.analyze_binding(targets, values)
                # Add iterator protocol edges for inner generators.
                # NOTE: gen.iter is visited again (already visited inside
                # analyze_binding); harmless — same node, edges deduplicate.
                inner_iter_node = self.visit(gen.iter)
                self._add_iterator_protocol_edges(inner_iter_node, is_async=gen.is_async)
                for expr in gen.ifs:
                    self.visit(expr)

            self.visit(getattr(node, field1))  # e.g. node.elt
            if field2:
                self.visit(getattr(node, field2))
        return scope_ctx.inner_scope_node

    def visit_Call(self, node):
        self.logger.debug("Call %s, %s:%s" % (get_ast_node_name(node.func), self.filename, node.lineno))

        # visit args to detect uses
        for arg in node.args:
            self.visit(arg)
        for kw in node.keywords:
            self.visit(kw.value)

        # see if we can predict the result
        try:
            result_node = self.resolve_builtins(node)
        except UnresolvedSuperCallError:
            result_node = None

        if isinstance(result_node, Node):  # resolved result
            from_node = self.get_node_of_current_namespace()
            to_node = result_node
            self.logger.debug("Use from %s to %s (via resolved call to built-ins)" % (from_node, to_node))
            if self.add_uses_edge(from_node, to_node):
                self.logger.info(
                    "New edge added for Use from %s to %s (via resolved call to built-ins)" % (from_node, to_node)
                )
            return result_node

        else:  # unresolved call — general case
            func_node = self.visit(node.func)

            # If the call target is a known class (e.g. MyClass()),
            # add a uses edge to MyClass.__init__().
            if func_node in self.class_base_ast_nodes:
                from_node = self.get_node_of_current_namespace()
                to_node = self.get_node(func_node.get_name(), "__init__", None, flavor=Flavor.METHOD)
                self.logger.debug("Use from %s to %s (call creates an instance)" % (from_node, to_node))
                if self.add_uses_edge(from_node, to_node):
                    self.logger.info(
                        "New edge added for Use from %s to %s (call creates an instance)" % (from_node, to_node)
                    )
            return func_node

    def _visit_with(self, node, enter_method, exit_method):
        """Shared implementation for With and AsyncWith."""
        self.logger.debug("With (context manager), %s:%s" % (self.filename, node.lineno))

        def add_uses_enter_exit_of(graph_node):
            if isinstance(graph_node, Node):
                from_node = self.get_node_of_current_namespace()
                withed_obj_node = graph_node

                self.logger.debug("Use from %s to With %s" % (from_node, withed_obj_node))
                for methodname in (enter_method, exit_method):
                    to_node = self.get_node(withed_obj_node.get_name(), methodname, None, flavor=Flavor.METHOD)
                    if self.add_uses_edge(from_node, to_node):
                        self.logger.info("New edge added for Use from %s to %s" % (from_node, to_node))

        for withitem in node.items:
            expr = withitem.context_expr
            vars = withitem.optional_vars

            # NOTE: expr is visited again inside analyze_binding() when vars is not None;
            # the double visit is harmless (resolves to the same node, edges deduplicate).
            cm_node = self.visit(expr)
            add_uses_enter_exit_of(cm_node)

            if vars is not None:
                # bind optional_vars
                #
                # TODO: For now, we support only the following (most common) case:
                #  - only one binding target, vars is ast.Name
                #    (not ast.Tuple or something else)
                #  - the variable will point to the object that was with'd
                #    (i.e. we assume the object's __enter__() method
                #     to finish with "return self")
                #
                if isinstance(vars, ast.Name):
                    self.analyze_binding(canonize_exprs(vars), canonize_exprs(expr))
                else:
                    self.visit(vars)  # just capture any uses on the With line itself

        for stmt in node.body:
            self.visit(stmt)

    def visit_With(self, node):
        self._visit_with(node, "__enter__", "__exit__")

    def visit_AsyncWith(self, node):
        self._visit_with(node, "__aenter__", "__aexit__")

    def visit_Delete(self, node):
        """Track protocol method calls implied by `del` statements.

        `del obj.attr` invokes `obj.__delattr__("attr")`.
        `del obj[key]` invokes `obj.__delitem__(key)`.
        `del name` just unbinds a local — no protocol call.

        NOTE: `del name` also invalidates prior value bindings for `name`,
        so a subsequent `name.attr` would be a NameError at runtime.  We do
        not clear the binding here because the analyzer is flow-insensitive —
        the `del` might sit in a branch that doesn't always execute, or come
        after the use in source order but not in control flow.  Clearing would
        be wrong as often as right.  Revisit if flow sensitivity is ever added.
        """
        self.logger.debug("Delete, %s:%s" % (self.filename, node.lineno))
        from_node = self.get_node_of_current_namespace()
        for target in node.targets:
            if isinstance(target, ast.Attribute):
                obj_node = self.visit(target.value)
                if isinstance(obj_node, Node):
                    to_node = self.get_node(obj_node.get_name(), "__delattr__", None, flavor=Flavor.METHOD)
                    self.logger.debug("Use from %s to %s (del attr)" % (from_node, to_node))
                    if self.add_uses_edge(from_node, to_node):
                        self.logger.info("New edge added for Use from %s to %s (del attr)" % (from_node, to_node))
            elif isinstance(target, ast.Subscript):
                obj_node = self.visit(target.value)
                if isinstance(obj_node, Node):
                    to_node = self.get_node(obj_node.get_name(), "__delitem__", None, flavor=Flavor.METHOD)
                    self.logger.debug("Use from %s to %s (del item)" % (from_node, to_node))
                    if self.add_uses_edge(from_node, to_node):
                        self.logger.info("New edge added for Use from %s to %s (del item)" % (from_node, to_node))
                # Also visit the slice — it may contain names/calls.
                self.visit(target.slice)
            # ast.Name in ast.Del context: just unbinds, no protocol call.

    # --- Match statement (PEP 634, Python 3.10+) ---

    def visit_Match(self, node):
        self.logger.debug("Match, %s:%s" % (self.filename, node.lineno))
        self.visit(node.subject)
        for case in node.cases:
            self.visit(case.pattern)
            if case.guard is not None:
                self.visit(case.guard)
            for stmt in case.body:
                self.visit(stmt)

    def visit_MatchValue(self, node):
        self.visit(node.value)

    def visit_MatchSingleton(self, node):
        pass

    def visit_MatchSequence(self, node):
        for pattern in node.patterns:
            self.visit(pattern)

    def visit_MatchMapping(self, node):
        for key in node.keys:
            self.visit(key)
        for pattern in node.patterns:
            self.visit(pattern)
        if node.rest is not None:
            self.set_value(node.rest, None)

    def visit_MatchClass(self, node):
        self.visit(node.cls)
        for pattern in node.patterns:
            self.visit(pattern)
        for pattern in node.kwd_patterns:
            self.visit(pattern)

    def visit_MatchStar(self, node):
        if node.name is not None:
            self.set_value(node.name, None)

    def visit_MatchAs(self, node):
        if node.pattern is not None:
            self.visit(node.pattern)
        if node.name is not None:
            self.set_value(node.name, None)

    def visit_MatchOr(self, node):
        for pattern in node.patterns:
            self.visit(pattern)

    ###########################################################################
    # Analysis helpers

    def analyze_functiondef(self, ast_node):
        """Analyze a function definition.

        Visit decorators, and if this is a method definition, capture the name
        of the first positional argument to denote "self", like Python does.

        Return (self_name, flavor), where self_name the name representing self,
        or None if not applicable; and flavor is a Flavor, specifically one of
        FUNCTION, METHOD, STATICMETHOD or CLASSMETHOD."""

        if not isinstance(ast_node, (ast.AsyncFunctionDef, ast.FunctionDef)):
            raise TypeError("Expected ast.FunctionDef; got %s" % (type(ast_node)))

        # Visit decorators
        deco_names = []
        for deco in ast_node.decorator_list:
            deco_node = self.visit(deco)
            if isinstance(deco_node, Node):
                deco_names.append(deco_node.name)

        # Analyze flavor
        in_class_ns = self.context_stack[-1].startswith("ClassDef")
        if not in_class_ns:
            flavor = Flavor.FUNCTION
        else:
            if "staticmethod" in deco_names:
                flavor = Flavor.STATICMETHOD
            elif "classmethod" in deco_names:
                flavor = Flavor.CLASSMETHOD
            else:  # instance method
                flavor = Flavor.METHOD

        # Get the name representing "self", if applicable.
        #
        # - ignore static methods
        # - ignore functions defined inside methods (this new FunctionDef
        #   must be directly in a class namespace)
        #
        if flavor in (Flavor.METHOD, Flavor.CLASSMETHOD):
            # We can treat instance methods and class methods the same,
            # since Pyan is only interested in object types, not instances.
            all_args = ast_node.args  # args, vararg (*args), kwonlyargs, kwarg (**kwargs)
            posargs = all_args.args
            if len(posargs):
                self_name = posargs[0].arg
                return self_name, flavor

        return None, flavor

    def _bind_target(self, target, value):
        """Bind an AST target node to a resolved value (a graph Node or None).

        Dispatches on target type: Name and Attribute perform scalar binding,
        Tuple/List recurse (all sub-targets get the same value), Starred
        unwraps to its inner target, and ast.arg handles function parameter
        defaults.
        """
        if isinstance(target, ast.Name):
            self.set_value(target.id, value)
        elif isinstance(target, ast.Attribute):
            try:
                if self.set_attribute(target, value):
                    self.logger.info("setattr %s.%s to %s" % (get_ast_node_name(target.value), target.attr, value))
            except UnresolvedSuperCallError:
                pass
        elif isinstance(target, (ast.Tuple, ast.List)):
            for elt in target.elts:
                self._bind_target(elt, value)
        elif isinstance(target, ast.Starred):
            self._bind_target(target.value, value)
        elif isinstance(target, ast.arg):
            self.set_value(target.arg, value)

    @staticmethod
    def _collect_target_names(target, names):
        """Collect all Name identifiers from an assignment target AST node."""
        if isinstance(target, ast.Name):
            names.add(target.id)
        elif isinstance(target, (ast.Tuple, ast.List)):
            for elt in target.elts:
                CallGraphVisitor._collect_target_names(elt, names)
        elif isinstance(target, ast.Starred):
            CallGraphVisitor._collect_target_names(target.value, names)

    def analyze_binding(self, targets, values):
        """Generic handler for binding forms. Inputs must be canonize_exprs()d."""
        captured = [self.visit(value) for value in values]
        if len(targets) == len(captured):
            for tgt, val in zip(targets, captured):
                self._bind_target(tgt, val)
        else:
            # Check for positional starred unpacking on LHS (e.g. a, b, *c = x, y, z, w).
            star_idx = None
            for i, tgt in enumerate(targets):
                if isinstance(tgt, ast.Starred):
                    if star_idx is not None:
                        star_idx = None  # multiple stars → give up
                        break
                    star_idx = i

            if star_idx is not None and len(captured) >= len(targets) - 1:
                # Positional matching: bind non-starred targets to their
                # positional counterparts, starred target to the remainder.
                n_before = star_idx
                n_after = len(targets) - star_idx - 1
                for tgt, val in zip(targets[:n_before], captured[:n_before]):
                    self._bind_target(tgt, val)
                if n_after > 0:
                    for tgt, val in zip(targets[-n_after:], captured[-n_after:]):
                        self._bind_target(tgt, val)
                star_end = len(captured) - n_after if n_after else len(captured)
                remainder = captured[n_before:star_end]
                if remainder:
                    for val in remainder:
                        self._bind_target(targets[star_idx], val)
                else:
                    self._bind_target(targets[star_idx], None)
            else:
                # No star, multiple stars, or too few values.
                # Overapproximate: each target gets every RHS value.
                # _bind_target handles Tuple/List/Starred recursion.
                # Skip logging when captured is a single value (e.g. for-loop
                # or comprehension binding multiple targets to one iterable) —
                # no combinatorial blowup, and it's the common case.
                if len(captured) > 1:
                    lineno = getattr(targets[0], "lineno", "?") if targets else "?"
                    self.logger.info("Cartesian fallback: %d targets, %d values, %s:%s"
                                     % (len(targets), len(captured), self.filename, lineno))
                for tgt in targets:
                    for val in captured:
                        self._bind_target(tgt, val)

    def resolve_builtins(self, ast_node):
        """Resolve those calls to built-in functions whose return values
        can be determined in a simple manner.

        Currently, this supports:

          - str(obj), repr(obj) --> obj.__str__, obj.__repr__

          - super() (any arguments ignored), which works only in pass 2,
            because the MRO is determined between passes.

        May raise UnresolvedSuperCallError, if the call is to super(),
        but the result cannot be (currently) determined (usually because either
        pass 1, or some relevant source file is not in the analyzed set).

        Returns the Node the call resolves to, or None if not determined.
        """
        if not isinstance(ast_node, ast.Call):
            raise TypeError("Expected ast.Call; got %s" % (type(ast_node)))

        func_ast_node = ast_node.func  # expr
        if isinstance(func_ast_node, ast.Name):
            funcname = func_ast_node.id
            if funcname == "super":
                class_node = self.get_current_class()
                self.logger.debug("Resolving super() of %s" % (class_node))
                if class_node in self.mro:
                    # Our super() class is the next one in the MRO.
                    #
                    # Note that we consider only the **static type** of the
                    # class itself. The later elements of the MRO - important
                    # for resolving chained super() calls in a dynamic context,
                    # where the dynamic type of the calling object is different
                    # from the static type of the class where the super() call
                    # site is - are never used by Pyan for resolving super().
                    #
                    # This is a limitation of pure lexical scope based static
                    # code analysis.
                    #
                    if len(self.mro[class_node]) > 1:
                        result = self.mro[class_node][1]
                        self.logger.debug("super of %s is %s" % (class_node, result))
                        return result
                    else:
                        msg = "super called for %s, but no known bases" % (class_node)
                        self.logger.info(msg)
                        raise UnresolvedSuperCallError(msg)
                else:
                    msg = "super called for %s, but MRO not determined for it (maybe still in pass 1?)" % (class_node)
                    self.logger.info(msg)
                    raise UnresolvedSuperCallError(msg)

            if funcname in ("str", "repr"):
                if len(ast_node.args) == 1:  # these take only one argument
                    obj_astnode = ast_node.args[0]
                    if isinstance(obj_astnode, (ast.Name, ast.Attribute)):
                        self.logger.debug("Resolving %s() of %s" % (funcname, get_ast_node_name(obj_astnode)))
                        attrname = "__%s__" % (funcname)
                        # build a temporary ast.Attribute AST node so that we can use get_attribute()
                        tmp_astnode = ast.Attribute(value=obj_astnode, attr=attrname, ctx=obj_astnode.ctx)
                        obj_node, attr_node = self.get_attribute(tmp_astnode)
                        self.logger.debug(
                            "Resolve %s() of %s: returning attr node %s"
                            % (funcname, get_ast_node_name(obj_astnode), attr_node)
                        )
                        return attr_node

            # add implementations for other built-in funcnames here if needed

    def resolve_attribute(self, ast_node):
        """Resolve an ast.Attribute.

        Nested attributes (a.b.c) are automatically handled by recursion.

        Return (obj,attrname), where obj is a Node (or None on lookup failure),
        and attrname is the attribute name.

        May pass through UnresolvedSuperCallError, if the attribute resolution
        failed specifically due to an unresolved super() call.
        """

        if not isinstance(ast_node, ast.Attribute):
            raise TypeError("Expected ast.Attribute; got %s" % (type(ast_node)))

        self.logger.debug(
            "Resolve %s.%s in context %s" % (get_ast_node_name(ast_node.value), ast_node.attr, type(ast_node.ctx))
        )

        # Resolve nested attributes
        #
        # In pseudocode, e.g. "a.b.c" is represented in the AST as:
        #    ast.Attribute(attr=c, value=ast.Attribute(attr=b, value=a))
        #
        if isinstance(ast_node.value, ast.Attribute):
            obj_node, attr_name = self.resolve_attribute(ast_node.value)

            if isinstance(obj_node, Node) and obj_node.namespace is not None:
                ns = obj_node.get_name()  # fully qualified namespace **of attr**
                if ns in self.scopes:  # imported modules not in the set of analyzed files are not seen by Pyan
                    sc = self.scopes[ns]
                    if attr_name in sc.defs:
                        self.logger.debug("Resolved to attr %s of %s" % (ast_node.attr, sc.defs[attr_name]))
                        return sc.defs[attr_name], ast_node.attr

            # It may happen that ast_node.value has no corresponding graph Node,
            # if this is a forward-reference, or a reference to a file
            # not in the analyzed set.
            #
            # In this case, return None for the object to let visit_Attribute()
            # add a wildcard reference to *.attr.
            #
            self.logger.debug("Unresolved, returning attr %s of unknown" % (ast_node.attr))
            return None, ast_node.attr
        else:
            # detect str.join() and similar (attributes of constant literals,
            # such as "hello".upper())
            if isinstance(ast_node.value, ast.Constant):
                theliteral = ast_node.value
                t = type(theliteral.value)
                tn = t.__name__
                # Create a namespace-like Node with no associated AST node.
                # Constants are builtins, so they should live in the
                # top-level namespace (same level as module names).
                #
                # Since get_node() creates only one node per unique
                # (namespace,name) pair, the AST node would anyway be
                # frozen to the first constant of any matching type that
                # the analyzer encountered in the analyzed source code,
                # which is not useful.
                #
                # The CLASS flavor is the best match, as these constants
                # are object types.
                #
                obj_node = self.get_node("", tn, None, flavor=Flavor.CLASS)

            # attribute of a function call. Detect cases like super().dostuff()
            elif isinstance(ast_node.value, ast.Call):
                # Note that resolve_builtins() will signal an unresolved
                # super() by an exception, which we just pass through here.
                obj_node = self.resolve_builtins(ast_node.value)

                # can't resolve result of general function call
                if not isinstance(obj_node, Node):
                    self.logger.debug("Unresolved function call as obj, returning attr %s of unknown" % (ast_node.attr))
                    return None, ast_node.attr
            else:
                # Get the Node object corresponding to node.value in the current ns.
                #
                # (Using the current ns here is correct; this case only gets
                #  triggered when there are no more levels of recursion,
                #  and the leftmost name always resides in the current ns.)
                obj_node = self.get_value(get_ast_node_name(ast_node.value))  # resolves "self" if needed

        self.logger.debug("Resolved to attr %s of %s" % (ast_node.attr, obj_node))
        return obj_node, ast_node.attr

    ###########################################################################
    # Scope analysis

    def analyze_scopes(self, code, filename):
        """Gather lexical scope information."""

        # Below, ns is the fully qualified ("dotted") name of sc.
        #
        # Technically, the module scope is anonymous, but we treat it as if
        # it was in a namespace named after the module, to support analysis
        # of several files as a set (keeping their module-level definitions
        # in different scopes, as we should).
        #
        scopes = {}

        def process(parent_ns, table):
            sc = Scope(table)
            ns = "%s.%s" % (parent_ns, sc.name) if len(sc.name) else parent_ns
            scopes[ns] = sc
            for t in table.get_children():
                process(ns, t)

        process(self.module_name, symtable.symtable(code, filename, compile_type="exec"))

        # add to existing scopes (while not overwriting any existing definitions with None)
        for ns in scopes:
            if ns not in self.scopes:  # add new scope info
                self.scopes[ns] = scopes[ns]
            else:  # update existing scope info
                sc = scopes[ns]
                oldsc = self.scopes[ns]
                for name in sc.defs:
                    if name not in oldsc.defs:
                        oldsc.defs[name] = sc.defs[name]

        self.logger.debug("Scopes now: %s" % (self.scopes))

    def get_current_class(self):
        """Return the node representing the current class, or None if not inside a class definition."""
        return self.class_stack[-1] if len(self.class_stack) else None

    def get_node_of_current_namespace(self):
        """Return the unique node representing the current namespace,
        based on self.name_stack.

        For a Node n representing a namespace:
          - n.namespace = fully qualified name of the parent namespace
                          (empty string if at top level)
          - n.name      = name of this namespace
          - no associated AST node.
        """
        assert len(self.name_stack)  # name_stack should never be empty (always at least module name)

        namespace = ".".join(self.name_stack[0:-1])
        name = self.name_stack[-1]
        return self.get_node(namespace, name, None, flavor=Flavor.NAMESPACE)

    ###########################################################################
    # Value getter and setter

    def get_value(self, name):
        """Get the value of name in the current scope. Return the Node, or None
        if name is not set to a value."""

        # get the innermost scope that has name **and where name has a value**
        def find_scope(name):
            for sc in reversed(self.scope_stack):
                if name in sc.defs and sc.defs[name] is not None:
                    return sc

        sc = find_scope(name)
        if sc is not None:
            value = sc.defs[name]
            if isinstance(value, Node):
                self.logger.info("Get %s in %s, found in %s, value %s" % (name, self.scope_stack[-1], sc, value))
                return value
            else:
                # TODO: should always be a Node or None
                self.logger.debug(
                    "Get %s in %s, found in %s: value %s is not a Node" % (name, self.scope_stack[-1], sc, value)
                )
        else:
            self.logger.debug("Get %s in %s: no Node value (or name not in scope)" % (name, self.scope_stack[-1]))

    def set_value(self, name, value):
        """Set the value of name in the current scope. Value must be a Node."""

        # get the innermost scope that has name (should be the current scope unless name is a global)
        def find_scope(name):
            for sc in reversed(self.scope_stack):
                if name in sc.defs:
                    return sc

        sc = find_scope(name)
        if sc is not None:
            if isinstance(value, Node):
                sc.defs[name] = value
                self.logger.info("Set %s in %s to %s" % (name, sc, value))
            else:
                # TODO: should always be a Node or None
                self.logger.debug("Set %s in %s: value %s is not a Node" % (name, sc, value))
        else:
            self.logger.debug("Set: name %s not in scope" % (name))

    ###########################################################################
    # Attribute getter and setter

    def get_attribute(self, ast_node):
        """Get value of an ast.Attribute.

        Supports inherited attributes. If the obj's own namespace has no match
        for attr, the ancestors of obj are also tried, following the MRO based
        on the static type of the object, until one of them matches or until
        all ancestors are exhausted.

        Return pair of Node objects (obj,attr), where each item can be None
        on lookup failure. (Object not known, or no Node value assigned
        to its attr.)

        May pass through UnresolvedSuperCallError.
        """

        if not isinstance(ast_node, ast.Attribute):
            raise TypeError("Expected ast.Attribute; got %s" % (type(ast_node)))
        if not isinstance(ast_node.ctx, ast.Load):
            raise ValueError("Expected a load context, got %s" % (type(ast_node.ctx)))

        obj_node, attr_name = self.resolve_attribute(ast_node)

        if isinstance(obj_node, Node) and obj_node.namespace is not None:
            ns = obj_node.get_name()  # fully qualified namespace **of attr**

            # detect str.join() and similar (attributes of constant literals)
            #
            # Any attribute is considered valid for these special types,
            # but only in a load context. (set_attribute() does not have this
            # special handling, by design.)
            #
            if ns in ("Num", "Str"):  # TODO: other types?
                return obj_node, self.get_node(ns, attr_name, None, flavor=Flavor.ATTRIBUTE)

            # look up attr_name in the given namespace, return Node or None
            def lookup(ns):
                if ns in self.scopes:
                    sc = self.scopes[ns]
                    if attr_name in sc.defs:
                        return sc.defs[attr_name]

            # first try directly in object's ns (this works already in pass 1)
            value_node = lookup(ns)
            if value_node is not None:
                return obj_node, value_node

            # next try ns of each ancestor (this works only in pass 2,
            # after self.mro has been populated)
            #
            if obj_node in self.mro:
                for base_node in tail(self.mro[obj_node]):  # the first element is always obj itself
                    ns = base_node.get_name()
                    value_node = lookup(ns)
                    if value_node is not None:
                        break
                else:
                    return None, None  # not found
                return base_node, value_node  # as obj, return the base class in which attr was found

        return obj_node, None  # here obj_node is either None or unknown (namespace None)

    def set_attribute(self, ast_node, new_value):
        """Assign the Node provided as new_value into the attribute described
        by the AST node ast_node. Return True if assignment was done,
        False otherwise.

        May pass through UnresolvedSuperCallError.
        """

        if not isinstance(ast_node, ast.Attribute):
            raise TypeError("Expected ast.Attribute; got %s" % (type(ast_node)))
        if not isinstance(ast_node.ctx, ast.Store):
            raise ValueError("Expected a store context, got %s" % (type(ast_node.ctx)))

        if not isinstance(new_value, Node):
            return False

        obj_node, attr_name = self.resolve_attribute(ast_node)

        if isinstance(obj_node, Node) and obj_node.namespace is not None:
            ns = obj_node.get_name()  # fully qualified namespace **of attr**
            if ns in self.scopes:
                sc = self.scopes[ns]
                sc.defs[attr_name] = new_value
                return True
        return False

    ###########################################################################
    # Graph creation

    def get_node(self, namespace, name, ast_node=None, flavor=Flavor.UNSPECIFIED):
        """Return the unique node matching the namespace and name.
        Create a new node if one doesn't already exist.

        To associate the node with a syntax object in the analyzed source code,
        an AST node can be passed in. This only takes effect if a new Node
        is created.

        To associate an AST node to an existing graph node,
        see associate_node().

        Flavor describes the kind of object the node represents.
        See the node.Flavor enum for currently supported values.

        For existing nodes, flavor overwrites, if the given flavor is
        (strictly) more specific than the node's existing one.
        See node.Flavor.specificity().

        !!!
        In CallGraphVisitor, always use get_node() to create nodes, because it
        also sets some important auxiliary information. Do not call the Node
        constructor directly.
        !!!
        """

        if name in self.nodes:
            for n in self.nodes[name]:
                if n.namespace == namespace:
                    if Flavor.specificity(flavor) > Flavor.specificity(n.flavor):
                        n.flavor = flavor
                    return n

        # Try to figure out which source file this Node belongs to
        # (for annotated output).
        #
        # Other parts of the analyzer may change the filename later,
        # if a more authoritative source (e.g. a definition site) is found,
        # so the filenames should be trusted only after the analysis is
        # complete.
        #
        # TODO: this is tentative. Add in filename only when sure?
        # (E.g. in visit_ClassDef(), visit_FunctionDef())
        #
        if namespace in self.module_to_filename:
            # If the namespace is one of the modules being analyzed,
            # the the Node belongs to the correponding file.
            filename = self.module_to_filename[namespace]
        else:  # Assume the Node belongs to the current file.
            filename = self.filename

        n = Node(namespace, name, ast_node, filename, flavor)

        # Add to the list of nodes that have this short name.
        if name in self.nodes:
            self.nodes[name].append(n)
        else:
            self.nodes[name] = [n]

        return n

    def get_parent_node(self, graph_node):
        """Get the parent node of the given Node. (Used in postprocessing.)"""
        if "." in graph_node.namespace:
            ns, name = graph_node.namespace.rsplit(".", 1)
        else:
            ns, name = "", graph_node.namespace
        return self.get_node(ns, name, None)

    def associate_node(self, graph_node, ast_node, filename=None):
        """Change the AST node (and optionally filename) mapping of a graph node.

        This is useful for generating annotated output with source filename
        and line number information.

        Sometimes a function in the analyzed code is first seen in a FromImport
        before its definition has been analyzed. The namespace can be deduced
        correctly already at that point, but the source line number information
        has to wait until the actual definition is found (because the line
        number is contained in the AST node). However, a graph Node must be
        created immediately when the function is first encountered, in order
        to have a Node that can act as a "uses" target (namespaced correctly,
        to avoid a wildcard and the over-reaching expand_unknowns() in cases
        where they are not needed).

        This method re-associates the given graph Node with a different
        AST node, which allows updating the context when the definition
        of a function or class is encountered."""
        graph_node.ast_node = ast_node
        if filename is not None:
            graph_node.filename = filename

    def add_defines_edge(self, from_node, to_node):
        """Add a defines edge in the graph between two nodes.
        N.B. This will mark both nodes as defined."""
        status = False
        if from_node not in self.defines_edges:
            self.defines_edges[from_node] = set()
            status = True
        from_node.defined = True
        if to_node is None or to_node in self.defines_edges[from_node]:
            return status
        self.defines_edges[from_node].add(to_node)
        to_node.defined = True
        return True

    def add_uses_edge(self, from_node, to_node):
        """Add a uses edge in the graph between two nodes."""

        if from_node not in self.uses_edges:
            self.uses_edges[from_node] = set()
        if to_node in self.uses_edges[from_node]:
            return False
        self.uses_edges[from_node].add(to_node)

        # for pass 2: remove uses edge to any matching wildcard target node
        # if the given to_node has a known namespace.
        #
        # Prevents the spurious reference to MyClass.f in this example:
        #
        # class MyClass:
        #     def __init__(self):
        #         pass
        #     def f():
        #         pass
        #
        # def main():
        #     f()
        #
        # def f():
        #     pass
        #
        # (caused by reference to *.f in pass 1, combined with
        #  expand_unknowns() in postprocessing.)
        #
        # TODO: this can still get confused. The wildcard is removed if the
        # name of *any* resolved uses edge matches, whereas the wildcard
        # may represent several uses, to different objects.
        #
        if to_node.namespace is not None:
            self.remove_wild(from_node, to_node, to_node.name)

        return True

    def remove_uses_edge(self, from_node, to_node):
        """Remove a uses edge from the graph. (Used in postprocessing.)"""

        if from_node in self.uses_edges:
            u = self.uses_edges[from_node]
            if to_node in u:
                u.remove(to_node)

    def remove_wild(self, from_node, to_node, name):
        """Remove uses edge from from_node to wildcard *.name.

        This needs both to_node and name because in case of a bound name
        (e.g. attribute lookup) the name field of the *target value* does not
        necessarily match the formal name in the wildcard.

        Used for cleaning up forward-references once resolved.
        This prevents spurious edges due to expand_unknowns()."""

        if name is None:  # relative imports may create nodes with name=None.
            return

        if from_node not in self.uses_edges:  # no uses edges to remove
            return

        # Keep wildcard if the target is actually an unresolved argument
        # (see visit_FunctionDef())
        if to_node.get_name().find("^^^argument^^^") != -1:
            return

        # Here we may prefer to err in one of two ways:
        #
        #  a) A node seemingly referring to itself is actually referring
        #     to somewhere else that was not fully resolved, so don't remove
        #     the wildcard.
        #
        #     Example:
        #
        #         import sympy as sy
        #         def simplify(expr):
        #             sy.simplify(expr)
        #
        #     If the source file of sy.simplify is not included in the set of
        #     analyzed files, this will generate a reference to *.simplify,
        #     which is formally satisfied by this function itself.
        #
        #     (Actually, after commit e3c32b782a89b9eb225ef36d8557ebf172ff4ba5,
        #      this example is bad; sy.simplify will be recognized as an
        #      unknown attr of a known object, so no wildcard is generated.)
        #
        #  b) A node seemingly referring to itself is actually referring
        #     to itself (it can be e.g. a recursive function). Remove the wildcard.
        #
        #     Bad example:
        #
        #         def f(count):
        #             if count > 0:
        #                 return 1 + f(count-1)
        #             return 0
        #
        #     (This example is bad, because visit_FunctionDef() will pick up
        #      the f in the top-level namespace, so no reference to *.f
        #      should be generated in this particular case.)
        #
        # We choose a).
        #
        # TODO: do we need to change our opinion now that also recursive calls are visualized?
        #
        if to_node == from_node:
            return

        matching_wilds = [n for n in self.uses_edges[from_node] if n.namespace is None and n.name == name]
        assert len(matching_wilds) < 2  # the set can have only one wild of matching name
        if len(matching_wilds):
            wild_node = matching_wilds[0]
            self.logger.info("Use from %s to %s resolves %s; removing wildcard" % (from_node, to_node, wild_node))
            self.remove_uses_edge(from_node, wild_node)

    ###########################################################################
    # Postprocessing

    def contract_nonexistents(self):
        """For all use edges to non-existent (i.e. not defined nodes) X.name, replace with edge to *.name."""

        new_uses_edges = []
        removed_uses_edges = []
        for n in self.uses_edges:
            for n2 in self.uses_edges[n]:
                if n2.namespace is not None and not n2.defined:
                    n3 = self.get_node(None, n2.name, n2.ast_node)
                    n3.defined = False
                    new_uses_edges.append((n, n3))
                    removed_uses_edges.append((n, n2))
                    self.logger.info("Contracting non-existent from %s to %s as %s" % (n, n2, n3))

        for from_node, to_node in new_uses_edges:
            self.add_uses_edge(from_node, to_node)

        for from_node, to_node in removed_uses_edges:
            self.remove_uses_edge(from_node, to_node)

    def expand_unknowns(self):
        """For each unknown node *.name, replace all its incoming edges with edges to X.name for all possible Xs.

        Also mark all unknown nodes as not defined (so that they won't be visualized)."""

        new_defines_edges = []
        for n in self.defines_edges:
            for n2 in self.defines_edges[n]:
                if n2.namespace is None:
                    for n3 in self.nodes[n2.name]:
                        if n3.namespace is not None:
                            new_defines_edges.append((n, n3))

        for from_node, to_node in new_defines_edges:
            self.add_defines_edge(from_node, to_node)
            self.logger.info("Expanding unknowns: new defines edge from %s to %s" % (from_node, to_node))

        new_uses_edges = []
        for n in self.uses_edges:
            for n2 in self.uses_edges[n]:
                if n2.namespace is None:
                    for n3 in self.nodes[n2.name]:
                        if n3.namespace is not None:
                            new_uses_edges.append((n, n3))

        for from_node, to_node in new_uses_edges:
            self.add_uses_edge(from_node, to_node)
            self.logger.info("Expanding unknowns: new uses edge from %s to %s" % (from_node, to_node))

        for name in self.nodes:
            for n in self.nodes[name]:
                if n.namespace is None:
                    n.defined = False

    def cull_inherited(self):
        """
        For each use edge from W to X.name, if it also has an edge to W to Y.name where
        Y is used by X, then remove the first edge.
        """

        removed_uses_edges = []
        for n in self.uses_edges:
            for n2 in self.uses_edges[n]:
                inherited = False
                for n3 in self.uses_edges[n]:
                    if (
                        n3.name == n2.name
                        and n2.namespace is not None
                        and n3.namespace is not None
                        and n3.namespace != n2.namespace
                    ):
                        pn2 = self.get_parent_node(n2)
                        pn3 = self.get_parent_node(n3)
                        # if pn3 in self.uses_edges and pn2 in self.uses_edges[pn3]:
                        # remove the second edge W to Y.name (TODO: add an option to choose this)
                        if pn2 in self.uses_edges and pn3 in self.uses_edges[pn2]:  # remove the first edge W to X.name
                            inherited = True

                if inherited and n in self.uses_edges:
                    removed_uses_edges.append((n, n2))
                    self.logger.info("Removing inherited edge from %s to %s" % (n, n2))

        for from_node, to_node in removed_uses_edges:
            self.remove_uses_edge(from_node, to_node)

    def collapse_inner(self):
        """Combine lambda and comprehension Nodes with their parent Nodes to reduce visual noise.
        Also mark those original nodes as undefined, so that they won't be visualized."""

        # Lambdas and comprehensions do not define any names in the enclosing
        # scope, so we only need to treat the uses edges.

        # BUG: resolve relative imports causes (RuntimeError: dictionary changed size during iteration)
        # temporary solution is adding list to force a copy of 'self.nodes'
        for name in list(self.nodes):
            if name in ("lambda", "listcomp", "setcomp", "dictcomp", "genexpr"):
                for n in self.nodes[name]:
                    pn = self.get_parent_node(n)
                    if n in self.uses_edges:
                        for n2 in self.uses_edges[n]:  # outgoing uses edges
                            self.logger.info("Collapsing inner from %s to %s, uses %s" % (n, pn, n2))
                            self.add_uses_edge(pn, n2)
                    n.defined = False
