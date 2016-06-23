# Copyright 2015 Intel Corporation
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import copy
import six
import sys

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import encodeutils

from keystoneclient import exceptions
from searchlight.common import config
from searchlight.common import utils
from searchlight.elasticsearch.plugins import utils as es_utils
from searchlight import i18n


CONF = cfg.CONF
LOG = logging.getLogger(__name__)
_ = i18n._
_LE = i18n._LE
_LI = i18n._LI
_LW = i18n._LW


# Decorators for actions
def args(*args, **kwargs):
    def _decorator(func):
        func.__dict__.setdefault('args', []).insert(0, (args, kwargs))
        return func
    return _decorator


class IndexCommands(object):
    def __init__(self):
        utils.register_plugin_opts()

    @args('--group', metavar='<group>', dest='group',
          help='Index only this Resource Group (or a comma separated list)')
    @args('--type', metavar='<type>', dest='_type',
          help='Index only this type (or a comma separated list)')
    @args('--force', dest='force', action='store_true',
          help="Don't prompt (answer 'y')")
    def sync(self, group=None, _type=None, force=False):
        # Verify all indices and types have registered plugins.
        # index and _type are lists because of nargs='*'
        group = group.split(',') if group else []
        _type = _type.split(',') if _type else []

        group_set = set(group)
        type_set = set(_type)

        """
        The caller can specify a sync based on either the Document Type or the
        Resource Group. With the Zero Downtime functionality, we are using
        aliases to index into ElasticSearch. We now have multiple Document
        Types sharing a single alias. If any member of a Resource Group (an
        ES alias) is re-syncing *all* members of that Resoruce Group needs
        to re-sync.

        The final list of plugins to use for re-syncing *must* come only from
        the Resource Group specifications. The "type" list is used only to make
        the "group" list complete. We need a two pass algorithm for this.

        First pass: Analyze the plugins according to the "type" list. This
          turns a type in the "type" list to a group in the "group" list.

        Second pass: Analyze the plugins according to the "group" list. Create
          the plugin list that will be used for re-syncing.

        Note: We cannot call any plugin's sync() during these two passes. The
        sync needs to be a separate step. The API states that if any invalid
        plugin was specified by the caller, the entire operation fails.
        """

        # First Pass: Document Types.
        if _type:
            for res_type, ext in six.iteritems(utils.get_search_plugins()):
                plugin_obj = ext.obj
                type_set.discard(plugin_obj.get_document_type())
                if plugin_obj.get_document_type() in _type:
                    group.append(plugin_obj.resource_group_name)

        # Second Pass: Resource Groups (including those from types).
        # This pass is a little tricky. If "group" is empty, it implies every
        # resource gets re-synced. The command group_set.discard() is a no-op
        # when "group" is empty.
        resource_groups = []
        plugin_objs = {}
        plugins_list = []
        for res_type, ext in six.iteritems(utils.get_search_plugins()):
            plugin_obj = ext.obj
            group_set.discard(plugin_obj.resource_group_name)
            if (not group) or (plugin_obj.resource_group_name in group):
                plugins_list.append((res_type, ext))
                plugin_objs[plugin_obj.resource_group_name] = plugin_obj
                if not (plugin_obj.resource_group_name,
                        plugin_obj.alias_name_search,
                        plugin_obj.alias_name_listener) in resource_groups:
                    resource_groups.append((plugin_obj.resource_group_name,
                                            plugin_obj.alias_name_search,
                                            plugin_obj.alias_name_listener))

        if group_set or type_set:
            print("Some index names or types do not have plugins "
                  "registered. Index names: %s. Types: %s" %
                  (",".join(group_set) or "<None>",
                   ",".join(type_set) or "<None>"))
            print("Aborting.")
            sys.exit(1)

        if not force:
            # For display purpose, we want to iterate on only parthenogenetic
            # plugins that are not the children of another plugin. If there
            # are children plugins they will be displayed when we call
            # get_index_display_name(). Therefore any child plugins in the
            # display list, will be listed twice.
            display_plugins = []
            for res, ext in plugins_list:
                if not ext.obj.parent_plugin:
                    display_plugins.append((res, ext))

            def format_selection(selection):
                resource_type, ext = selection
                return '  ' + ext.obj.get_index_display_name()

            # Grab the first element in the first (and only) tuple.
            group = resource_groups[0][0]
            print("\nAll resource types within Resource Group \"%(group)s\""
                  " must be re-indexed" % {'group': group})
            print("\nResource types matching selection:\n%s\n" %
                  '\n'.join(map(format_selection, sorted(display_plugins))))

            ans = raw_input(
                "Indexing will NOT delete existing data or mapping(s). It "
                "will reindex all resources. \nUse '--force' to suppress "
                "this message.\nOK to continue? [y/n]: ")
            if ans.lower() != 'y':
                print("Aborting.")
                sys.exit(0)

        # Start the re-indexing process

        # Step #1: Create new indexes for each Resource Group Type.
        #   The index needs to be fully functional before it gets
        #   added to any aliases. This inclues all settings and
        #   mappings. Only then can we add it to the aliases. We first
        #   need to create all indexes. This is done by resource group.
        #   Once all indexes are created, we need to initialize the
        #   indexes. This is done by document type.
        #   NB: The aliases remain unchanged for this step.
        index_names = {}
        try:
            for group, search, listen in resource_groups:
                index_names[group] = es_utils.create_new_index(group)
            for resource_type, ext in plugins_list:
                plugin_obj = ext.obj
                group_name = plugin_obj.resource_group_name
                plugin_obj.prepare_index(index_name=index_names[group_name])
        except Exception:
            LOG.error(_LE("Error creating index or mapping, aborting "
                          "without indexing"))
            es_utils.alias_error_cleanup(index_names)
            raise

        # Step #2: Set up the aliases for all Resource Type Group.
        #   These actions need to happen outside of the plugins. Now that
        #   the indexes are created and fully functional we can associate
        #   them with the aliases.
        #   NB: The indexes remain unchanged for this step.
        for group, search, listen in resource_groups:
            try:
                es_utils.setup_alias(index_names[group], search, listen)
            except Exception as e:
                LOG.error(_LE("Failed to setup alias for resource group "
                              "%(g)s: %(e)s") % {'g': group, 'e': e})
                es_utils.alias_error_cleanup(index_names)
                raise

        # Step #3: Re-index all resource types in this Resource Type Group.
        #   As an optimization, if any types are explicitly requested, we
        #   will index them from their service APIs. The rest will be
        #   indexed from an existing ES index, if one exists.
        #   NB: The "search" and "listener" aliases remain unchanged for this
        #       step.
        es_reindex = []
        plugins_to_index = copy.copy(plugins_list)
        if _type:
            for resource_type, ext in plugins_list:
                doc_type = ext.obj.get_document_type()
                if doc_type not in _type:
                    es_reindex.append(doc_type)
                    plugins_to_index.remove((resource_type, ext))

        # Call plugin API as needed.
        if plugins_to_index:
            for res, ext in plugins_to_index:
                plugin_obj = ext.obj
                gname = plugin_obj.resource_group_name
                try:
                    plugin_obj.initial_indexing(index_name=index_names[gname])
                except exceptions.EndpointNotFound:
                    LOG.warning(_LW("Service is not available for plugin: "
                                    "%(ext)s") % {"ext": ext.name})
                except Exception as e:
                    LOG.error(_LE("Failed to setup index extension "
                                  "%(ex)s: %(e)s") % {'ex': ext.name, 'e': e})
                    es_utils.alias_error_cleanup(index_names)
                    raise

        # Call ElasticSearch for the rest, if needed.
        if es_reindex:
            for group in index_names.keys():
                # Grab the correct tuple as a list, convert list to a single
                # tuple, extract second member (the search alias) of tuple.
                alias_search = \
                    [a for a in resource_groups if a[0] == group][0][1]
                try:
                    es_utils.reindex(src_index=alias_search,
                                     dst_index=index_names[group],
                                     type_list=es_reindex)
                except Exception as e:
                    LOG.error(_LE("Failed to setup index extension "
                                  "%(ex)s: %(e)s") % {'ex': ext.name, 'e': e})
                    es_utils.alias_error_cleanup(index_names)
                    raise

        # Step #4: Update the "search" alias.
        #   All re-indexing has occurred. The index/alias is the same for
        #   all resource types within this Resource Group. These actions need
        #   to happen outside of the plugins.
        #   NB: The "listener" alias remains unchanged for this step.
        old_index = {}
        for group, search, listen in resource_groups:
            old_index[group] = \
                es_utils.alias_search_update(search, index_names[group])

        # Step #5: Update the "listener" alias.
        #   The "search" alias has been updated. This involves both removing
        #   the old index from the alias as well as deleting the old index.
        #   These actions need to happen outside of the plugins.
        #   NB: The "search" alias remains unchanged for this step.
        for group, search, listen in resource_groups:
            es_utils.alias_listener_update(listen, old_index[group])


def add_command_parsers(subparsers):
    """Adds any commands and subparsers for their actions. This code's
    from the Glance equivalent.
    """
    for command_name, cls in six.iteritems(COMMANDS):
        command_object = cls()

        parser = subparsers.add_parser(command_name)
        parser.set_defaults(command_object=command_object)

        command_subparsers = parser.add_subparsers(dest='action')

        for (action, action_fn) in methods_of(command_object):
            parser = command_subparsers.add_parser(action)

            action_kwargs = []
            for args, kwargs in getattr(action_fn, 'args', []):
                if kwargs['dest'].startswith('action_kwarg_'):
                    action_kwargs.append(
                        kwargs['dest'][len('action_kwarg_'):])
                else:
                    action_kwargs.append(kwargs['dest'])
                    kwargs['dest'] = 'action_kwarg_' + kwargs['dest']

                parser.add_argument(*args, **kwargs)

            parser.set_defaults(action_fn=action_fn)
            parser.set_defaults(action_kwargs=action_kwargs)

            parser.add_argument('action_args', nargs='*')


command_opt = cfg.SubCommandOpt('command',
                                title='Commands',
                                help='Available commands',
                                handler=add_command_parsers)


COMMANDS = {
    'index': IndexCommands
}


def methods_of(obj):
    """Get all callable methods of an object that don't start with underscore

    returns a list of tuples of the form (method_name, method)
    """
    result = []
    for i in dir(obj):
        if callable(getattr(obj, i)) and not i.startswith('_'):
            result.append((i, getattr(obj, i)))
    return result


def main():
    CONF.register_cli_opt(command_opt)
    if len(sys.argv) < 2:
        script_name = sys.argv[0]
        print("%s command action [<args>]" % script_name)
        print(_("Available commands:"))
        for command in COMMANDS:
            print(_("\t%s") % command)
        sys.exit(2)

    try:
        logging.register_options(CONF)

        cfg_files = cfg.find_config_files(project='searchlight',
                                          prog='searchlight')
        config.parse_args(default_config_files=cfg_files)
        config.set_config_defaults()
        logging.setup(CONF, 'searchlight')

        func_kwargs = {}
        for k in CONF.command.action_kwargs:
            v = getattr(CONF.command, 'action_kwarg_' + k)
            if v is None:
                continue
            if isinstance(v, six.string_types):
                v = encodeutils.safe_decode(v)
            func_kwargs[k] = v
        func_args = [encodeutils.safe_decode(arg)
                     for arg in CONF.command.action_args]
        return CONF.command.action_fn(*func_args, **func_kwargs)

    except RuntimeError as e:
        sys.exit("ERROR: %s" % e)


if __name__ == '__main__':
    main()
