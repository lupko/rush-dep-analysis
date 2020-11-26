import json
import sys

import json5
import os

from typing import List, Dict

#
# Basic types & loading from rush.json and package.json's
#
import yaml


class RushProject:
    def __init__(self, root, project):
        self._root = root
        self._project = project

    @property
    def project_folder(self):
        return self._project["projectFolder"]

    @property
    def package_name(self):
        return self._project["packageName"]

    @property
    def dir(self):
        return os.path.join(self._root, self.project_folder)

    @property
    def is_published(self):
        return 'shouldPublish' in self._project and self._project["shouldPublish"]

    def get_lockfile_entry_name(self):
        pkg_name = self.project_folder.split('/')[1]

        return "file:projects/%s.tgz" % pkg_name

    def get_package_json(self):
        return read_package_json(os.path.join(self._root, self.project_folder))


class PackageJson:
    def __init__(self, filename, content):
        self._filename = filename
        self._content = content

    @property
    def pkg(self):
        return self._content["name"]

    @property
    def pkg_id(self):
        return "%s/%s" % (self._content["name"], self._content["version"])

    @property
    def prod(self):
        if "dependencies" not in self._content:
            return []

        return list(self._content["dependencies"].items())

    @property
    def dev(self):
        if "devDependencies" not in self._content:
            return []

        return list(self._content["devDependencies"].items())

    @property
    def peer(self):
        if "peerDependencies" not in self._content:
            return []

        return list(self._content["peerDependencies"].items())

    @property
    def license(self):
        if "license" in self._content:
            license = self._content["license"]

            if isinstance(license, str):
                # spaces in n-quad subject/object will mess things up
                return self._content["license"].replace(' ', '-')
            else:
                return "UNKNOWN"
        else:
            print("%s has no license indication (see: %s)" % (self.pkg_id, self._filename))

    @property
    def description(self):
        if "description" in self._content:
            return self._content["description"].replace("\"", "'")

        return None

    @property
    def author(self):
        if "author" in self._content:
            return self._content["author"]

        return None

    @property
    def repository(self):
        if "repository" in self._content:
            repo = self._content["repository"]

            if isinstance(repo, str):
                return repo
            elif "url" in repo:
                return repo["url"]

        return None

    @property
    def keywords(self):
        if "keywords" in self._content:
            return self._content["keywords"]

        return []

    def is_prod_dep(self, pkg):
        return "dependencies" in self._content and pkg in self._content["dependencies"]

    def is_dev_dep(self, pkg):
        return "devDependencies" in self._content and pkg in self._content["devDependencies"]

    def is_peer_dep(self, pkg):
        return "peerDependencies" in self._content and pkg in self._content["peerDependencies"]

    def is_optional_peer_dep(self, pkg):
        if "peerDependenciesMeta" in self._content:
            peer_meta = self._content["peerDependenciesMeta"]

            return pkg in peer_meta and "optional" in peer_meta[pkg] and peer_meta[pkg]["optional"]

        return False

    def get_dep_type(self, dep):
        if self.is_prod_dep(dep):
            return "prod"
        elif self.is_dev_dep(dep):
            return "dev"
        elif self.is_peer_dep(dep):
            return "peer"
        elif self.is_optional_peer_dep(dep):
            return "opt_peer"
        else:
            raise ValueError("Unable to determine what type of dependency is between %s and %s" % (self.pkg, dep))

    def __str__(self):
        return "%(pkg)s prod=%(prod)d dev=%(dev)d" % dict(pkg=self.pkg.ljust(50, ' '), prod=len(self.prod),
                                                          dev=len(self.dev))


class PnpmLock:
    def __init__(self, lockfile):
        self._lockfile = lockfile
        self._rush_projects = self._locate_rush_projects()

    def _locate_rush_projects(self):
        """
        rush / pnpm may scope the rush project package with a dependency.
        instead of the expected key such as file:projects/project.tgz there will be something like
        file:projects/project.tgz_3rdpartypackage@version

        such scoped entry contains 'id' property with the expected unscoped identifier.

        this function will prance through all the packages and construct a unified mapping between expected
        rush project entry key and the actual rush project entry key.
        :return:
        """
        result = dict()

        for key, value in self.packages.items():
            if not key.startswith('file:projects/'):
                continue

            if 'id' in value and value['id'].startswith('file:projects/'):
                result[value['id']] = key
            else:
                result[key] = key

        return result

    @property
    def packages(self) -> Dict:
        return self._lockfile["packages"]

    @property
    def package_names(self):
        return self._lockfile["packages"].keys()

    def get_package_entry(self, package, ver):
        return self._lockfile["packages"]["/".join((package, ver))]

    def get_rush_project(self, prj: RushProject):
        # one layer of indirection due to dynamic nature of rush project entry keys in the lockfile
        # see _locate_rush_projects
        actual_key = self._rush_projects[prj.get_lockfile_entry_name()]

        return self._lockfile["packages"][actual_key]


def load_rush_projects(dirname) -> List[RushProject]:
    with open(os.path.join(dirname, "rush.json"), 'r') as rj:
        return list([RushProject(dirname, project) for project in json5.load(rj)['projects']])


def read_package_json(dirname) -> PackageJson:
    filename = os.path.join(dirname, "package.json")
    with open(filename, 'r') as rp:
        return PackageJson(filename, json.load(rp))


def load_package_jsons(projects: List[RushProject]) -> List[PackageJson]:
    return list([read_package_json(prj.dir) for prj in projects])


def load_pnpm_lock(dirname) -> PnpmLock:
    with open(os.path.join(dirname, 'common', 'config', 'rush', 'pnpm-lock.yaml'), 'r') as f:
        return PnpmLock(yaml.load(f))


#
# Code to create full dependency graph as n-quads that can be loaded to cayley
#

class PackageNode:
    def __init__(self, repo_dir, name, rush_project=None):
        self._repo_dir = repo_dir
        self._name = name
        self._rush_project: RushProject = rush_project
        self._versions = dict()

    def _read_package_json(self, ver) -> PackageJson:
        if self._rush_project:
            return self._rush_project.get_package_json()

        split_pkg = self._name.split('/')
        # root for all packages is in common/temp/node_modules/.pnpm
        package_version_dir = os.path.join(self._repo_dir, 'common', 'temp', 'node_modules', '.pnpm')

        if len(split_pkg) == 2:
            # packages with org can be found in the pnpm structure as follows:
            # group/package@version/node_modules/group/version/package.json
            #
            package_version_dir = os.path.join(package_version_dir, split_pkg[0], "%s@%s" % (split_pkg[1], ver),
                                               'node_modules', split_pkg[0], split_pkg[1])
        else:
            # packages without org can be found in the pnpm structure as follows:
            # package@version/node_modules/package/package.json
            package_version_dir = os.path.join(package_version_dir, "%s@%s" % (split_pkg[0], ver), 'node_modules',
                                               split_pkg[0])

        return read_package_json(package_version_dir)

    def add_version(self, ver):
        try:
            self._versions[ver] = self._read_package_json(ver)
        except FileNotFoundError as e:
            # an installed package @ version will have a directory & package.json in node_modules
            # if this happens, then there is nothing for this package version, meaning it is not installed
            # meaning it is most likely an optional dependency
            print("Likely optional dependency: " + str(e))

    def should_include(self):
        # installed packages have at least one version on disk (see add_version for more)
        return len(self._versions) or self._rush_project

    def get_dep_type(self, ver, dep):
        if ver not in self._versions:
            return None

        pkg_json = self._versions[ver]

        return pkg_json.get_dep_type(dep)

    def _version_quads(self, ver, pkg_json: PackageJson):
        result = list()
        license = pkg_json.license

        version_id = "%s/%s" % (self._name, ver)
        result.append("<%s> <has_version> <%s> .\n" % (self._name, version_id))
        result.append("<%s> <name> \"%s\" .\n" % (version_id, ver))
        result.append("<%s> <license> \"%s\" .\n" % (version_id, license if license else "UNKNOWN"))

        # storing descriptions may lead to silent fail (infinite load?) while loading to caley. unsure
        # why.. probably a bad character somewhere that knocks the parser off-balance
        #
        # if pkg_json.description is not None:
        #     result.append("<%s> <description> \"%s\" .\n" % (version_id, pkg_json.description))

        if pkg_json.repository is not None:
            result.append("<%s> <lives_in> <%s> .\n" % (version_id, pkg_json.repository))

        for keyword in pkg_json.keywords:
            result.append("<%s> <keyword> \"%s\" .\n" % (version_id, keyword))

        result.append("<%s> <has_role> <dependency> .\n" % (version_id))

        return result

    def _rush_project_nquads(self):
        result = list()

        if self._rush_project is None:
            return result

        visibility = "public" if self._rush_project.is_published else "private"
        result.append("<%s> <has_visibility> <%s> .\n" % (self._name, visibility))
        result.append("<%s> <has_role> <primary> .\n" % (self._name))

        return result

    def nquads(self):
        result = list()

        result.append("<%s> <name> \"%s\" .\n" % (self._name, self._name))

        if self._rush_project is None:
            result.append("<%s> <has_role> <package> .\n" % (self._name))

        result.extend([quad for ver, pkg_json in self._versions.items() for quad in self._version_quads(ver, pkg_json)])
        result.extend(self._rush_project_nquads())

        return result


def get_name_version_from_pnpm_key(pnpm_key: str):
    # typical entry in pnpm lock looks like this:
    #   /@storybook/components/5.3.21_@types+react@16.9.49:
    #   /wrap-ansi/6.2.0:
    # do the needful to get just the package name, sans the first / and the version
    split_id = pnpm_key.split('/')
    name = "/".join(split_id[1:len(split_id) - 1])
    version = split_id[len(split_id) - 1]

    return name, version


def discover_packages(repo_dir, rush_projects: List[RushProject], pnpm_lock: PnpmLock) -> Dict[str, PackageNode]:
    result = dict()
    rush_entries_in_lock = dict({prj.get_lockfile_entry_name(): True for prj in rush_projects})

    for prj in rush_projects:
        result[prj.package_name] = PackageNode(repo_dir, prj.package_name, prj)

    # first pass - identify package nodes & versions
    for pkg in pnpm_lock.package_names:
        # rush projects have some pseudo-entries in pnpm lock. ignore them. there is special processing for them
        if pkg in rush_entries_in_lock:
            continue

        name, version = get_name_version_from_pnpm_key(pkg)

        if name in result:
            node = result[name]
            node.add_version(version)
        else:
            node = PackageNode(repo_dir, name)
            node.add_version(version)

            result[name] = node

    return result


def discover_edges(nodes: Dict[str, PackageNode], pnpm_lock: PnpmLock, rush_projects: List[RushProject]):
    rush_entries_in_lock = dict({prj.get_lockfile_entry_name(): True for prj in rush_projects})

    for source_id, entry in pnpm_lock.packages.items():
        if source_id in rush_entries_in_lock:
            continue

        if 'dependencies' not in entry:
            continue

        source_name, source_version = get_name_version_from_pnpm_key(source_id)

        if source_name not in nodes:
            print(
                "Source of dependency - %s - does not have any existing node entry. Likely an optional dep with stub entry in lock file." % source_name)
            continue

        source_node = nodes[source_name]

        if not source_node.should_include():
            continue

        for dep, ver in entry['dependencies'].items():
            dep_id = "%s/%s" % (dep, ver)
            dep_type = source_node.get_dep_type(source_version, dep)

            if dep_type is None:
                print("Something is wrong: there is no package json for source of dependency at this version: %s" % (
                    source_id))

            if dep not in nodes:
                print("Dependency from %s to unknown package %s" % (source_name, dep_id))

            yield source_id[1:], dep_id, dep_type


def discover_edges_from_rush_packages(nodes: Dict[str, PackageNode], pnpm_lock: PnpmLock,
                                      rush_projects: List[RushProject]):
    rush_pkgs = {pkg.package_name: True for pkg in rush_projects}

    for project in rush_projects:
        lock_entry = pnpm_lock.get_rush_project(project)
        pkg_json = project.get_package_json()
        source_name = pkg_json.pkg

        # lock-file has all dependencies marked as prod; which is not true though. so this code
        # cross-checks with package.json to correctly assign the dependency type
        for dep, ver in lock_entry['dependencies'].items():
            dep_id = "%s/%s" % (dep, ver)
            dep_type = pkg_json.get_dep_type(dep)

            if dep not in nodes:
                print("Dependency from %s to unknown package %s" % (source_name, dep_id))

            yield source_name, dep_id, dep_type

        #
        # intra-repo dependencies are not included in the lockfile. explicitly add dependencies that may exist between
        # packages managed by rush
        #

        for dep, _ in pkg_json.prod:
            if dep in rush_pkgs:
                yield source_name, dep, "prod"

        for dep, _ in pkg_json.dev:
            if dep in rush_pkgs:
                yield source_name, dep, "dev"

        for dep, _ in pkg_json.peer:
            if dep in rush_pkgs:
                yield source_name, dep, "peer"


def edge_nquad(edge):
    source_id, dep_id, dep_type = edge

    return "<%s> <depends_%s> <%s> .\n" % (source_id, dep_type, dep_id)


def create_graph(repo_dir, output_dir):
    rush_projects = load_rush_projects(repo_dir)
    pnpm_lock = load_pnpm_lock(repo_dir)

    package_nodes = discover_packages(repo_dir, rush_projects, pnpm_lock)

    with open(os.path.join(output_dir, "deps.nq"), "wt") as fw:
        [fw.writelines(pkg_node.nquads()) for pkg_node in package_nodes.values() if pkg_node.should_include()]
        [fw.write(edge_nquad(edge)) for edge in discover_edges(package_nodes, pnpm_lock, rush_projects)]
        [fw.write(edge_nquad(edge)) for edge in
         discover_edges_from_rush_packages(package_nodes, pnpm_lock, rush_projects)]


#
# Entry point
#

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Specify two arguments: path to repo root and output directory")
        sys.exit(1)
    else:
        create_graph(sys.argv[1], sys.argv[2])
