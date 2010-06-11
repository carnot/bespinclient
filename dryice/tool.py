# ***** BEGIN LICENSE BLOCK *****
# Version: MPL 1.1/GPL 2.0/LGPL 2.1
#
# The contents of this file are subject to the Mozilla Public License Version
# 1.1 (the "License"); you may not use this file except in compliance with
# the License. You may obtain a copy of the License at
# http://www.mozilla.org/MPL/
#
# Software distributed under the License is distributed on an "AS IS" basis,
# WITHOUT WARRANTY OF ANY KIND, either express or implied. See the License
# for the specific language governing rights and limitations under the
# License.
#
# The Original Code is Bespin.
#
# The Initial Developer of the Original Code is
# Mozilla.
# Portions created by the Initial Developer are Copyright (C) 2009
# the Initial Developer. All Rights Reserved.
#
# Contributor(s):
#
# Alternatively, the contents of this file may be used under the terms of
# either the GNU General Public License Version 2 or later (the "GPL"), or
# the GNU Lesser General Public License Version 2.1 or later (the "LGPL"),
# in which case the provisions of the GPL or the LGPL are applicable instead
# of those above. If you wish to allow use of your version of this file only
# under the terms of either the GPL or the LGPL, and not to allow others to
# use your version of this file under the terms of the MPL, indicate your
# decision by deleting the provisions above and replace them with the notice
# and other provisions required by the GPL or the LGPL. If you do not delete
# the provisions above, a recipient may use your version of this file under
# the terms of any one of the MPL, the GPL or the LGPL.
#
# ***** END LICENSE BLOCK *****


import sys
import os
import optparse
import subprocess
import codecs
from wsgiref.simple_server import make_server

try:
    from json import loads, dumps
except ImportError:
    from simplejson import loads, dumps

from dryice.path import path

from dryice import plugins, combiner

class BuildError(Exception):
    def __init__(self, message, errors=None):
        if errors:
            message += "\n"
            for e in errors:
                message += "* %s\n" % (e)
        Exception.__init__(self, message)
                

sample_dir = path(__file__).dirname() / "samples"
_boot_file = path(__file__).dirname() / "boot.js"

def ignore_css(src, names):
    return [name for name in names if name.endswith(".css")]

class Manifest(object):
    """A manifest describes what should be built."""
    
    unbundled_plugins = None
    
    def __init__(self, include_tests=False, plugins=None, static_plugins=None,
        dynamic_plugins=None, worker_plugins=None, jquery="builtin",
        search_path=None, output_dir="build", include_sample=False,
        boot_file=None, unbundled_plugins=None, preamble=None, loader=None,
        worker=None, config=None):
        
        # backwards compatibility for "plugins"
        if plugins is None:
            plugins = []
        
        if static_plugins is not None:
            plugins.extend(static_plugins)
        
        static_plugins = plugins
        
        if dynamic_plugins is None:
            dynamic_plugins = []

        if worker_plugins is None:
            worker_plugins = []
            
        self.include_tests = include_tests
        static_plugins.insert(0, "bespin")
        self.static_plugins = static_plugins
        self.dynamic_plugins = dynamic_plugins
        worker_plugins.insert(0, "bespin")
        self.worker_plugins = worker_plugins
        
        self.jquery = jquery

        if search_path is not None:
            for i in range(0, len(search_path)):
                name = search_path[i]

                # did we get handed a dict already?
                if not isinstance(name, basestring):
                    continue

                # convert to the dict format that is used by
                # the plugin module
                search_path[i] = dict(name=name, path=path(name))
        else:
            search_path = []

        # add the default plugin directory, if it exists
        plugindir = path("plugins")
        if plugindir.exists():
            for name in plugindir.glob("*"):
                if not name.isdir():
                    continue
                search_path.append(dict(name=name, path=name))

        self.search_path = search_path

        if boot_file:
            self.boot_file = path(boot_file).abspath()
        else:
            self.boot_file = _boot_file

        if not output_dir:
            raise BuildError("""Cannot run unless output_dir is set
(it defaults to 'build'). The contents of the output_dir directory
will be deleted before the build.""")
        self.output_dir = path(output_dir)

        self.include_sample = include_sample
        
        if unbundled_plugins:
            self.unbundled_plugins = path(unbundled_plugins).abspath()

        self.preamble = path(__file__).dirname() / "preamble.js"

        def location_of(file, default_location):
            if default_location is not None:
                return path(default_location)
            static_path = path("static") / file
            return static_path if static_path.exists() else path("lib") / file

        self.loader = location_of("tiki.js", loader)
        self.worker = location_of("worker.js", worker)
        
        self.config = config if config is not None else {}
            
    @classmethod
    def from_json(cls, json_string, overrides=None):
        """Takes a JSON string and creates a Manifest object from it."""
        try:
            data = loads(json_string)
        except ValueError:
            raise BuildError("The manifest is not legal JSON: %s" % (json_string))
        scrubbed_data = dict()

        # you can't call a constructor with a unicode object
        for key in data:
            scrubbed_data[str(key)] = data[key]

        if overrides:
            scrubbed_data.update(overrides)

        return cls(**scrubbed_data)
    
    def _find_plugins(self):
        self._plugin_catalog = dict((p.name, p) for p in plugins.find_plugins(self.search_path))
        
        if self.jquery == "global":
            self._plugin_catalog['jquery'] = plugins.Plugin("jquery",
                path(__file__).dirname() / "globaljquery.js",
                dict(name="thirdparty"))

        errors = []

        for plugin in self.static_plugins + self.dynamic_plugins:
            if not plugin in self._plugin_catalog:
                errors.append("Plugin %s not found" % plugin)

        return errors

    @property
    def errors(self):
        try:
            return self._errors
        except AttributeError:
            self._errors = self._find_plugins()
            return self._errors

    def get_plugin(self, name):
        """Retrieve a plugin by name."""
        return self._plugin_catalog[name]

    def get_package(self, name):
        """Retrieve a combiner.Package by name."""
        plugin = self.get_plugin(name)
        return combiner.Package(plugin.name, plugin.dependencies)

    def generate_output_files(self, output_js, output_css, output_worker_js,
            static_packages=None, dynamic_packages=None, worker_packages=None):
        """Generates the combined JavaScript file, putting the
        output into output_file."""
        output_dir = self.output_dir

        if self.errors:
            raise BuildError("Errors found, stopping...", self.errors)

        output_js.write(self.preamble.text('utf8'))
        output_js.write(self.loader.text('utf8'))

        exclude_tests = not self.include_tests

        # finally, package up the plugins

        if static_packages is None or dynamic_packages is None or \
                worker_packages is None:
            dynamic_packages, static_packages, worker_packages = \
                self.get_package_lists()

        def process(package, output, dynamic):
            plugin = self.get_plugin(package.name)
            if dynamic:
                plugin_subdir = path("plugins")
                plugin_dir = output_dir / plugin_subdir
                if not plugin_dir.isdir():
                    plugin_dir.makedirs()
                plugin_filename = package.name + ".js"
                plugin_location = plugin_subdir / plugin_filename
                self._created_javascript.add(plugin_location)
                combine_output_path = plugin_dir / plugin_filename
                combine_output = combine_output_path.open("w")
            else:
                plugin_location = None
                combine_output = output

            combiner.write_metadata(output, plugin, plugin_location)

            combiner.combine_files(combine_output, output_css, plugin,
                                   plugin.location,
                                   exclude_tests=exclude_tests,
                                   image_path_prepend="resources/%s/"
                                                      % plugin.name)
            if dynamic:
                combine_output.write("bespin.tiki.script(%s);" %
                    dumps(plugin_filename))

        for package in dynamic_packages:
            process(package, output_js, True)
        for package in static_packages:
            process(package, output_js, False)

        def make_plugin_metadata(packages):
            md = dict()
            for p in packages:
                plugin = self.get_plugin(p.name)
                md[plugin.name] = plugin.metadata
            return dumps(md)

        # include plugin metadata
        # this comes after the plugins, because some plugins
        # may need to be importable at the time the metadata
        # becomes available.
        all_packages = static_packages + dynamic_packages + worker_packages
        all_md = make_plugin_metadata(all_packages)
        bundled_plugins = set([ p.name for p in all_packages ])
        self.bundled_plugins = bundled_plugins

        output_js.write("""
document.addEventListener("DOMContentLoaded", function() {
    bespin.tiki.require("bespin:plugins").catalog.loadMetadata(%s);;
}, false);
""" % all_md)
        
        if self.boot_file:
            boot_text = self.boot_file.text("utf8")
            boot_text = boot_text % (dumps(self.config),)
            output_js.write(boot_text.encode("utf8"))

        output_worker_js.write("bespin = {};\n")
        output_worker_js.write(self.loader.text("utf8"))

        for package in worker_packages:
            process(package, output_worker_js, False)

        worker_md = make_plugin_metadata(worker_packages)
        output_worker_js.write("bespin.metadata = %s;" % worker_md)

        output_worker_js.write(self.worker.text("utf8"))

    def get_dependencies(self, packages, root_names):
        """Given a dictionary of package names to packages, returns the list of
        root packages and all their dependencies, topologically sorted."""
        visited = set()
        result = []
        def visit(name):
            if name in visited:
                return
            visited.add(name)

            pkg = packages[name]
            for dep_name in pkg.dependencies:
                visit(dep_name)
            result.append(pkg)

        for name in root_names:
            visit(name)

        return result

    def get_package_lists(self):
        """Returns a tuple consisting of the dynamic plugins, the static
        plugins, and the worker plugins, in that order, along with all of their
        dependencies."""
        # Filter the packages into static and dynamic parts. If a package is
        # dynamically loaded, all of its dependencies must also be dynamically
        # loaded.
        def closure(plugins):
            to_visit = plugins
            pkgs = {}
            for name in to_visit:
                if name in pkgs:
                    continue
                pkg = self.get_package(name)
                pkgs[name] = pkg
                to_visit += pkg.dependencies
            return pkgs

        pkgs = closure(self.dynamic_plugins + self.static_plugins)
        dynamic_packages = self.get_dependencies(pkgs, self.dynamic_plugins)
        dynamic_names = set([ pkg.name for pkg in dynamic_packages ])

        deps = self.get_dependencies(pkgs, self.static_plugins)
        static_packages = [ p for p in deps if p.name not in dynamic_names ]

        pkgs = closure(self.worker_plugins)
        worker_packages = self.get_dependencies(pkgs, self.worker_plugins)

        return dynamic_packages, static_packages, worker_packages
        
    def _output_unbundled_plugins(self, output_dir):
        if not output_dir.exists():
            output_dir.makedirs()
        else:
            if not output_dir.isdir():
                raise BuildError("Unbundled plugins can't go in %s because it's not a directory" % output_dir)

        bundled_plugins = self.bundled_plugins
        for name, plugin in self._plugin_catalog.items():
            if name in bundled_plugins:
                continue
            location = plugin.location
            if location.isdir():
                location.copytree(output_dir / location.basename())
            else:
                location.copy(output_dir / location.basename())
        print "Unbundled plugins placed in: %s" % output_dir
                

    def build(self):
        """Run the build according to the instructions in the manifest.
        """
        if self.errors:
            raise BuildError("Errors found, stopping...", self.errors)
        
        output_dir = self.output_dir
        print "Placing output in %s" % output_dir
        if output_dir.exists():
            output_dir.rmtree()

        output_dir.makedirs()

        dynamic_packages, static_packages, worker_packages = \
            self.get_package_lists()
        
        self._created_javascript = set()

        filenames = [
            output_dir / f for f in
            ("BespinEmbedded.js", "BespinEmbedded.css", "worker.js")
        ]
        
        self._created_javascript.add(filenames[0])
        self._created_javascript.add(filenames[2])
        
        files = [ codecs.open(f, 'w', 'utf8') for f in filenames ]
        [ jsfile, cssfile, workerfile ] = files
        self.generate_output_files(jsfile, cssfile, workerfile,
            static_packages, dynamic_packages, worker_packages)
        for f in files:
            f.close()
        
        if self.unbundled_plugins:
            self._output_unbundled_plugins(self.unbundled_plugins)

        for package in static_packages + dynamic_packages + worker_packages:
            plugin = self.get_plugin(package.name)
            resources = plugin.location / "resources"
            if resources.exists() and resources.isdir():
                resources.copytree(output_dir / "resources" / plugin.name,
                    ignore=ignore_css)

        if self.include_sample:
            sample_dir.copytree(output_dir / "samples")

    def compress_js(self, compressor):
        """Compress the output using Closure Compiler."""
        for f in self._created_javascript:
            print "Compressing %s" % (f)
            compressed = f + ".compressed"
            subprocess.call("java -jar %s "
                "--js=%s"
                " --js_output_file=%s"
                " --warning_level=QUIET" % (compressor, f, f + ".compressed"),
                shell=True)
            if compressed.size == 0:
                raise BuildError("File %s did not compile correctly. Check for errors." % (f))
            newname = f.splitext()[0] + ".uncompressed.js"
            f.rename(newname)
            compressed.rename(f)
            

    def compress_css(self, compressor):
        """Compress the CSS using YUI Compressor."""
        print "Compressing CSS with YUI Compressor"
        compressor = path(compressor).abspath()
        subprocess.call("java -jar %s"
            " --type css -o BespinEmbedded.compressed.css"
            " BespinEmbedded.css" % compressor, shell=True,
            cwd=self.output_dir)


def main(args=None):
    if args is None:
        args = sys.argv

    print "dryice: the Bespin build tool"
    parser = optparse.OptionParser(
        description="""Builds fast-loading JS and CSS packages.""")
    parser.add_option("-j", "--jscompressor", dest="jscompressor",
        help="path to Closure Compiler to compress the JS output")
    parser.add_option("-c", "--csscompressor", dest="csscompressor",
        help="path to YUI Compressor to compress the CSS output")
    parser.add_option("-D", "--variable", dest="variables",
        action="append",
        help="override values in the manifest (use format KEY=VALUE, where VALUE is JSON)")
    parser.add_option("-s", "--server", dest="server",
        help="starts a server on [address:]port. example: -s 8080")
    options, args = parser.parse_args(args)

    overrides = {}
    if options.variables:
        for setting in options.variables:
            key, value = setting.split("=")
            overrides[key] = loads(value)

    if len(args) > 1:
        filename = args[1]
    else:
        filename = "manifest.json"

    filename = path(filename)
    if not filename.exists():
        raise BuildError("Build manifest file (%s) does not exist" % (filename))

    print "Using build manifest: ", filename
    
    if options.server:
        start_server(filename, options, overrides)
    else:
        do_build(filename, options, overrides)

index_html = """
<!DOCTYPE html>
<html><head>

<link href="BespinEmbedded.css" type="text/css" rel="stylesheet">

<script type="text/javascript" src="BespinEmbedded.js"></script>
</head>
<body style="height: 100%; width: 100%; margin: 0">
<div id="editor" class="bespin" data-bespinoptions='{ "settings": { "tabstop": 4 }, "syntax": "js", "stealFocus": true }' style="width: 500px; height: 500px">// The text of this div shows up in the editor.
var thisCode = "what shows up in the editor";
function editMe() {
 alert("and have fun!");
}
</div>
</body>
</html>
"""

class DryIceAndWSGI(object):
    def __init__(self, filename, options, overrides):
        from static import Cling

        self.filename = filename
        self.options = options
        self.overrides = overrides
        
        manifest = Manifest.from_json(filename.text())
        self.static_app = Cling(manifest.output_dir)
        
    def __call__(self, environ, start_response):
        path_info = environ.get("PATH_INFO", "")
        if not path_info or path_info == "/index.html" or path_info == "/":
            headers = [
                ('Content-Type', 'text/html'),
                ('Content-Length', str(len(index_html)))
            ]
            if environ['REQUEST_METHOD'] == "HEAD":
                headers.append(('Allow', 'GET, HEAD'))
                start_response("200 OK", headers)
                return ['']
            else:
                start_response("200 OK", headers)
                do_build(self.filename, self.options, self.overrides)
                return [index_html]
        else:
            return self.static_app(environ, start_response)

def start_server(filename, options, overrides):
    """Starts the little webserver"""
    app = DryIceAndWSGI(filename, options, overrides)
    server_option = options.server
    if ":" in server_option:
        host, port = server_option.split(":")
    else:
        host = "localhost"
        port = server_option
    port = int(port)
    print "Server started on %s, port %s" % (host, port)
    try:
        make_server(host, port, app).serve_forever()
    except KeyboardInterrupt:
        pass
    
def do_build(filename, options, overrides):
    """Runs the actual build"""
    try:
        manifest = Manifest.from_json(filename.text(), overrides=overrides)
        manifest.build()

        if options.jscompressor:
            manifest.compress_js(options.jscompressor)

        if options.csscompressor:
            manifest.compress_css(options.csscompressor)
    except BuildError, e:
        print "Build aborted: %s" % (e)

