#  Copyright (c) 2015-2017 Cisco Systems, Inc.

#  Permission is hereby granted, free of charge, to any person obtaining a copy
#  of this software and associated documentation files (the "Software"), to
#  deal in the Software without restriction, including without limitation the
#  rights to use, copy, modify, merge, publish, distribute, sublicense, and/or
#  sell copies of the Software, and to permit persons to whom the Software is
#  furnished to do so, subject to the following conditions:
#
#  The above copyright notice and this permission notice shall be included in
#  all copies or substantial portions of the Software.
#
#  THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
#  IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
#  FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
#  AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
#  LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
#  FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
#  DEALINGS IN THE SOFTWARE.

import copy
import collections
import os

import m9dicts

from molecule import ansible_playbook
from molecule import util


class Ansible(object):
    """
    `Ansible`_ is the default provisioner.  No other provisioner will be
    supported.

    Molecule uses Ansible to manage instances by executing playbooks.  The
    playbook names can be changed by overriding the defaults.

    .. code-block:: yaml

        provisioner:
          name: ansible
            setup: create.yml
            converge: playbook.yml
            teardown: destroy.yml

    A subset of Molecule subcommands have prerequisite tasks, which will run
    before the subcommand.  These can be changed by overriding the defaults.

    .. code-block:: yaml

        provisioner:
          name: ansible
            check_sequence:
              - create
              - converge
              - check
            converge_sequence:
              - create
              - converge
            test_sequence:
              - destroy
              - dependency
              - syntax
              - create
              - converge
              - idempotence
              - lint
              - verify
              - destroy

    Additional options can be passed to `ansible-playbook` through the options
    dict.  Any option set in this section will override the defaults.

    .. code-block:: yaml

        provisioner:
          name: ansible
          options:
            debug: True

    Modifying ansible.cfg.

    .. code-block:: yaml

        provisioner:
          name: ansible
          config_options:
            defaults:
              fact_caching: jsonfile
            ssh_connection:
              scp_if_ssh: True

    Roles which require host/groups to have certain variables set.  Molecule
    uses the same `variables defined in a playbook`_ syntax as `Ansible`_.

    .. code-block:: yaml

        provisioner:
          name: ansible
          group_vars:
            foo1:
              foo: bar
            foo2:
              foo: bar
              baz:
                qux: zzyzx
          host_vars:
            foo1-01:
              foo: bar

    .. _`variables defined in a playbook`: http://docs.ansible.com/ansible/playbooks_variables.html#variables-defined-in-a-playbook
    """  # noqa

    def __init__(self, config):
        """
        A class encapsulating the provisioner.

        :param config: An instance of a Molecule config.
        :return: None
        """
        self._config = config

    @property
    def default_config_options(self):
        """
        Default options provided to construct ansible.cfg and returns a dict.

        :return: dict
        """
        return {
            'defaults': {
                'ansible_managed':
                'Ansible managed: Do NOT edit this file manually!',
                'retry_files_enabled': False,
                'roles_path': '../../../../:$ANSIBLE_ROLES_PATH',
                'library':
                '{}:$ANSIBLE_LIBRARY'.format(self._get_libraries_directory()),
                'filter_plugins': '{}:$ANSIBLE_FILTER_PLUGINS'.format(
                    self._get_filter_plugin_directory()),
            }
        }

    @property
    def default_options(self):
        """
        Default CLI arguments provided to `ansible-playbook` and returns a
        dict.

        :return: dict
        """
        d = {}
        if self._config.args.get('debug'):
            d['debug'] = True

        return d

    @property
    def name(self):
        return self._config.config['provisioner']['name']

    @property
    def config_options(self):
        return self._config.merge_dicts(
            self.default_config_options,
            self._config.config['provisioner']['config_options'])

    @property
    def options(self):
        return self._config.merge_dicts(
            self.default_options,
            self._config.config['provisioner']['options'])

    @property
    def host_vars(self):
        return self._config.config['provisioner']['host_vars']

    @property
    def group_vars(self):
        return self._config.config['provisioner']['group_vars']

    @property
    def inventory(self):
        """
        Create an inventory structure and returns a dict.

        .. code-block:: yaml
            ungrouped:
              vars:
                foo: bar
              hosts:
                instance-1-default:
                instance-2-default:
              children:
                $child_group_name:
                  hosts:
                    instance-1-default:
                    instance-2-default:
            $group_name:
              hosts:
                instance-1-default:
                  ansible_connection: docker
                instance-2-default:
                  ansible_connection: docker

        :return: str
        """
        dd = self._vivify()
        for platform in self._config.platforms.instances_with_scenario_name:
            for group in platform.get('groups', ['ungrouped']):
                instance_name = platform['name']
                connection_options = self._config.driver.connection_options(
                    instance_name)
                dd[group]['hosts'][instance_name] = connection_options
                dd['ungrouped']['vars'] = {
                    'molecule_file': self._config.molecule_file,
                    'molecule_inventory_file': self.inventory_file,
                    'molecule_scenario_directory':
                    self._config.scenario.directory,
                    'molecule_instance_config':
                    self._config.driver.instance_config,
                }
                # Child groups
                for child_group in platform.get('children', []):
                    dd[group]['children'][child_group]['hosts'][
                        instance_name] = connection_options

        return dd

    @property
    def inventory_file(self):
        return os.path.join(self._config.ephemeral_directory,
                            'ansible_inventory.yml')

    @property
    def config_file(self):
        return os.path.join(self._config.ephemeral_directory, 'ansible.cfg')

    def converge(self, playbook, **kwargs):
        """
        Executes `ansible-playbook` and returns a string.

        :param playbook: A string containing an absolute path to a
         provisioner's playbook.
        :param kwargs: Optional keyword arguments.
        :return: str
        """
        pb = self._get_ansible_playbook(playbook, **kwargs)
        return pb.execute()

    def syntax(self, playbook):
        """
        Executes `ansible-playbook` syntax check and returns None.

        :param playbook: A string containing an absolute path to a
         provisioner's playbook.
        :return: None
        """
        pb = self._get_ansible_playbook(playbook)
        pb.add_cli_arg('syntax-check', True)
        pb.execute()

    def check(self, playbook):
        """
        Executes `ansible-playbook` check and returns None.

        :param playbook: A string containing an absolute path to a
         provisioner's playbook.
        :return: None
        """
        pb = self._get_ansible_playbook(playbook)
        pb.add_cli_arg('check', True)
        pb.execute()

    def write_inventory(self):
        """
        Writes the provisioner's inventory file to disk and returns None.

        :return: None
        """
        self._verify_inventory()

        # Convert the dictlike object to a dict for safe dumping.
        inventory = m9dicts.convert_to(self.inventory)
        util.write_file(self.inventory_file, util.safe_dump(inventory))

    def write_config(self):
        """
        Writes the provisioner's config file to disk and returns None.

        :return: None
        """
        # self._verify_config()

        template = util.render_template(
            self._get_config_template(), config_options=self.config_options)
        util.write_file(self.config_file, template)

    def add_or_update_vars(self, target):
        """
        Creates host and/or group vars and returns None.

        :param target: A string containing either `host_vars` or `group_vars`.
        :returns: None
        """
        if target == 'host_vars':
            vars_target = copy.deepcopy(self.host_vars)
            # Append the scenario-name
            for instance_name, _ in self.host_vars.items():
                instance_with_scenario_name = util.instance_with_scenario_name(
                    instance_name, self._config.scenario.name)
                vars_target[instance_with_scenario_name] = vars_target.pop(
                    instance_name)

        elif target == 'group_vars':
            vars_target = self.group_vars

        if not vars_target:
            return

        ephemeral_directory = self._config.ephemeral_directory
        target_vars_directory = os.path.join(ephemeral_directory, target)

        if not os.path.isdir(os.path.abspath(target_vars_directory)):
            os.mkdir(os.path.abspath(target_vars_directory))

        for target in vars_target.keys():
            target_var_content = vars_target[target]
            path = os.path.join(os.path.abspath(target_vars_directory), target)
            util.write_file(path, util.safe_dump(target_var_content))

    def _get_ansible_playbook(self, playbook, **kwargs):
        """
        Get an instance of AnsiblePlaybook and returns it.

        :param playbook: A string containing an absolute path to a
         provisioner's playbook.
        :param kwargs: Optional keyword arguments.
        :return: object
        """
        return ansible_playbook.AnsiblePlaybook(self.inventory_file, playbook,
                                                self._config, **kwargs)

    def _verify_inventory(self):
        """
        Verify the inventory is valid and returns None.

        :return: None
        """
        if not self.inventory:
            msg = ("Instances missing from the 'platform' "
                   "section of molecule.yml.")
            util.sysexit_with_message(msg)

    def _get_config_template(self):
        """
        Returns a config template string.

        :return: str
        """
        return """
{% for section, section_dict in config_options.items() -%}
[{{ section }}]
{% for k, v in section_dict.items() -%}
{{ k }} = {{ v }}
{% endfor -%}
{% endfor -%}
""".strip()

    def _vivify(self):
        """
        Return an autovivification default dict.

        :return: dict
        """
        return collections.defaultdict(self._vivify)

    def _get_plugin_directory(self):
        return os.path.join(
            os.path.dirname(__file__), '..', '..', 'molecule', 'provisioner',
            'ansible', 'plugins')

    def _get_libraries_directory(self):
        return os.path.join(self._get_plugin_directory(), 'libraries')

    def _get_filter_plugin_directory(self):
        return os.path.join(self._get_plugin_directory(), 'filters')
