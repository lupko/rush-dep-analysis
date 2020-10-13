# Dependency analysis for Rush monorepo projects

This is a rough developer tooling to aid with analysis of _installed_ dependency chains in a monorepo managed by Rush and pnpm.

The general idea is as follows:

1.  Shovels through contents of `rush.json`, `pnpm-lock.yaml` and package.json files of the installed dependencies
2.  Create dependency graph
3.  Load the graph into Cayley
4.  Let developer analyze the graph using Cayley web interface

## Getting started

1.  Clone the repository
2.  Run `prepare_graph.sh` script with two parameters:
    -  Path to rush repository; remember: the repo must be in valid, post `rush install` state
    -  Path to directory where to dump the graph. Cayley will read from `data` dir so best to put it there.
    
    Example: `./prepare_graph.sh ../your_rush_repo data`
3.  Start Cayley backend: `./start_db.sh`
4.  Start Cayley frontend: `./start_ui.sh`
5.  Open `http://localhost:3666` in your browser

## Graph

The tooling works with a graph of physically installed package versions and dependencies between them. For
each installed package version, there are edges describing what are its installed dependencies and what type
of dependency brought them in.

> Note: the packages managed by the Rush monorepo are treated as primary packages - roots - from which
> all dependencies originate. The graph does not concern itself with versions of the primary packages.

The dependency graph is represented as a list of [n-quads](https://en.wikipedia.org/wiki/N-Triples). This is one of 
the formats that Cayley understands. Bonus is that this is a dialect of RDF; you can use for instance python's `rdflib`
to read the graph (`rdflib.ConjunctiveGraph()` and use format `turtle`). 

Here is a quick description the content - subject, object and predicate types:

-  For each package in the Rush repository:

   -  `<package_name> <name> "package_name"`
   -  `<package_name> <has_visibility> <private|public>`
      
      If the package is published to NPM, it will have 'public' visiblity. Otherwise 'private' visibility. This is
      determined from rush.json entry for the package. It's based on 'shouldPublish' property.
         
   -  `<package_name> <has_role> <primary>`
   
      All packages implemented in Rush monorepo are predicates as primary.
   
   -  `<package_name> <depends_TYPE> <package_name>`
   
      There will be one n-quad for each dependency between packages managed in the same Rush monorepo.
   
   -  `<package_name> <depends_TYPE> <package_name/version>`
   
      There will be one n-quad for each installed dependency. There are multiple depends predicates, one
      for each type of dependency. See below for more information.
      
-  For installed third party dependencies:

   -  `<package_name> <name> "package_name"`
   -  `<package_name> <has_role> <package_name>`
   -  `<package_name> <has_version> <package_name/version>` 
   
      There will be one n-quad for each installed version of the package.
      
   -  `<package_name/version> <name> "version"`
   -  `<package_name/version> <has_role> <dependency>`
   
      All installed third party dependencies have this role.
   
   -  `<package_name/version> <license> "LICENSE"`
   
      Content of package.json license property.
   
   -  `<package_name/version> <depends_TYPE> <package_name/version>`
   
      There will be one n-quad for each installed dependency. There are multiple depends predicates, one
      for each type of dependency. See below for more information.
      
   -  `<package_name/version> <lives_in> <repository_url>`
   
      Content of package.json repository / repository.url property
   
   -  `<package_name/version> <keyword> "keyword"`
   
      There will be one n-quad for each keyword listed in package's package.json.
      
The following dependency predicates are supported:

-  `depends_prod` - production dependency
-  `depends_dev` - dev dependency
-  `depends_peer` - peer dependency
-  `depends_opt_peer` - optional peer dependency (as found in peerDependenciesMeta)

## Analyzing the graph in Cayley

The [Gizmo API](https://github.com/cayleygraph/cayley/blob/master/docs/gizmoapi.md) is a nice and flexible
way to work with the graph. The documentation is sparse and it may take some time to familiarize with the
concepts.

> Note: Cayley has default limit of returning 100 results. It is possible to use `getLimit()` to get all results
> or do paging using `skip` and `limit` functions. However, there is still limitation where forEach() will always
> halt after 100 results. It is thus not possible to make some more complex reports with subqueries.  

Here are couple of examples that may help you learn by example.

### Trivial stuff

**List primary packages**

```javascript
g.V()
.has("<has_role>", "<primary>")
.all();
```

**List primary packages which are published to NPM**

```javascript
g.V()
.has("<has_role>", "<primary>")
.has("<has_visibility>", "<public>")
.all();
```

**Number of unique packages that the primary packages depend on**

```javascript
var res = g.V()
.has("<has_role>", "<package>")
.count();
```

**Number of installed package versions that the primary packages depend on**

```javascript
var res = g.V()
.has("<has_role>", "<dependency>")
.count();
```

### Traversal

**Find all prod dependencies of publicly visible packages**
```javascript

// follow out edges of type "depends_prod" IF the target has 'dependency' role (e.g. is third party dep)
var prodDeps = g
  .Morphism()
  .out("<depends_prod>")
  .has("<has_role>", "<dependency>");

// start with primary, public packages, then from each follow the third-party prod-dep-path all the way 
// to the end
g.V()
.has("<has_role>", "<primary>")
.has("<has_visibility>", "<public>")
.followRecursive(prodDeps)
.all();
```

**Find all packages that depend on some installed package**

```javascript
var reverseProdDeps = g
  .Morphism()
  .in("<depends_prod>");

g.V("<rxjs/5.5.12>")
.followRecursive(prodDeps)
.all()
```

### Result processing / nested queries

**Find all prod dependencies of publicly visible packages, print them together with their license**

```javascript
// follow out edges of type "depends_prod" IF the target has 'dependency' role (e.g. is third party dep)
var prodDeps = g
  .Morphism()
  .out("<depends_prod>")
  .has("<has_role>", "<dependency>");

g.V()
.has("<has_role>", "<primary>")
.has("<has_visibility>", "<public>")
.followRecursive(prodDeps)
.forEach(function(d) {
    // each production third party dependency will be dispatched to this function
    var id = d.id["@id"];
    
    // take the dependency, and run query to obtain its license - follow the `license` predicate
    g.V("<" + id + ">").out("<license>").forEach(function(lic) {
        // print stuff
        // note: license is stored in graph as literal ("MIT", "BSD") and not as an URI (<>). That
        // is why it is accessed as lic.id instead of the further nesting under @id
        g.emit({ package: id, license: lic.id })
    });
})
```

## Analyzing the graph in sqlite

The `prepare_graph.sh` script will also create `deps.sqlite` database with the graph. See [sqlite.ddl](./graph/sqlite.ddl) to
learn about available relations and built-in views.

Working with sqlite has better reporting capabilities compared to Cayley approach. However the traversals are somewhat
tricky and often way slower.

**Find installed versions of some package**

```sql
SELECT * FROM installed_versions WHERE package = 'node-forge';
```

**Find packages which have more than one version installed**

```sql
SELECT * from install_counts WHERE installs > 1 ORDER BY package ASC;
```

**Get licences of all installed packages**

```sql
SELECT * from licenses ORDER BY package_version ASC;
```

**Who depends on particular package version**

```sql
WITH RECURSIVE reverse_deps(from_id, to_id, type, path, level) AS (
    SELECT
        e.from_id,
        e.to_id,
        e.type,
        e.from_id || ',' AS path,
        1 AS level
    FROM edge e
             INNER JOIN node fn on fn.id = e.to_id AND fn.value = 'node-forge/0.7.5'
    WHERE e.type IN ('depends_dev', 'depends_prod')
    UNION ALL
    SELECT
        e1.from_id,
        e1.to_id,
        e1.type,
        r.path || e1.from_id || ',' AS path,
        r.level + 1 AS level
    FROM edge e1, reverse_deps r
    WHERE e1.to_id = r.from_id AND e1.type IN ('depends_dev', 'depends_prod')
)
SELECT n.value AS dependening, MIN(d.level) AS level from reverse_deps d
INNER JOIN node n ON n.id = d.from_id
GROUP BY n.value
ORDER BY level ASC;
```
