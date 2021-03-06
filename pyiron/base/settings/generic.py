# coding: utf-8
# Copyright (c) Max-Planck-Institut für Eisenforschung GmbH - Computational Materials Design (CM) Department
# Distributed under the terms of "New BSD License", see the LICENSE file.

from builtins import input
import os
from six import with_metaclass
import sys
from pathlib2 import Path
from pyiron.base.settings.logger import setup_logger
from pyiron.base.database.generic import DatabaseAccess
from pyiron.base.settings.install import install_pyiron

"""
The settings file provides the attributes of the configuration as properties.
"""

__author__ = "Jan Janssen"
__copyright__ = "Copyright 2019, Max-Planck-Institut für Eisenforschung GmbH - " \
                "Computational Materials Design (CM) Department"
__version__ = "1.0"
__maintainer__ = "Jan Janssen"
__email__ = "janssen@mpie.de"
__status__ = "production"
__date__ = "Sep 1, 2017"

# Depending on the Python Version - a specific version of the config parser is required.
if sys.version_info.major == 2:
    from ConfigParser import ConfigParser
else:
    from configparser import ConfigParser


class Singleton(type):
    """
    Implemented with suggestions from

    http://stackoverflow.com/questions/6760685/creating-a-singleton-in-python

    """
    _instances = {}

    def __call__(cls, *args, **kwargs):
        if kwargs is not None and 'config' in kwargs.keys() and kwargs['config'] is not None:
            cls._instances[cls] = super(Singleton, cls).__call__(*args, **kwargs)
        if cls not in cls._instances:
            cls._instances[cls] = super(Singleton, cls).__call__(*args, **kwargs)
        return cls._instances[cls]


class Settings(with_metaclass(Singleton)):
    """
    The settings object can either search for an configuration file and use the default configuration only when no
    other configuration file is found, or it can be forced to use the default configuration file.

    Args:
        config (dict): Provide a dict with the configuration.
    """
    def __init__(self, config=None):
        # Default config dictionary
        self._configuration = {'user': 'pyiron',
                               'resource_paths': ['~/pyiron/resources'],
                               'project_paths': ['~/pyiron/projects'],
                               'sql_connection_string': None,
                               'sql_table_name': 'jobs_pyiron',
                               'sql_view_connection_string': None,
                               'sql_view_table_name': None,
                               'sql_view_user': None,
                               'sql_view_user_key': None,
                               'sql_file': None,
                               'sql_host': None,
                               'sql_type': 'SQLite',
                               'sql_user_key': None,
                               'sql_database': None}
        environment_keys = os.environ.keys()
        if 'PYIRONCONFIG' in environment_keys:
            config_file = environment_keys['PYIRONCONFIG']
        else:
            config_file = os.path.expanduser(os.path.join("~", ".pyiron"))
        if os.path.isfile(config_file):
            self._config_parse_file(config_file)
        elif not any([env in environment_keys
                      for env in ['TRAVIS', 'APPVEYOR', 'CIRCLECI', 'CONDA_BUILD', 'GITLAB_CI']]):
            user_input = None
            while user_input not in ['yes', 'no']:
                user_input = input('It appears that pyiron is not yet configured, do you want to create a default start configuration (recommended: yes). [yes/no]:')
            if user_input.lower() == 'yes' or user_input.lower() == 'y':
                install_pyiron(config_file_name=config_file,
                               zip_file="resources.zip",
                               resource_directory="~/pyiron/resources",
                               giturl_for_zip_file="https://github.com/pyiron/pyiron-resources/archive/master.zip",
                               git_folder_name="pyiron-resources-master")
            else:
                raise ValueError('pyiron was not installed!')
            self._config_parse_file(config_file)

        # Take dictionary as primary source - overwrite everything
        if isinstance(config, dict):
            for key, value in config.items():
                if key not in ['resource_paths', 'project_paths'] or isinstance(value, list):
                    self._configuration[key] = value
                elif isinstance(value, str):
                    self._configuration[key] = [value]
                else:
                    TypeError('Config dictionary parameter type not recognized ', key, value)

        self._configuration['project_paths'] = [convert_path(path) + '/' if path[-1] != '/' else convert_path(path)
                                                for path in self._configuration['project_paths']]
        self._configuration['resource_paths'] = [convert_path(path)
                                                for path in self._configuration['resource_paths']]   

        # Build the SQLalchemy connection strings
        if self._configuration['sql_type'] == 'Postgres':
            self._configuration['sql_connection_string'] = 'postgresql://' + self._configuration['user'] + ':' \
                                                           + self._configuration['sql_user_key'] + '@' \
                                                           + self._configuration['sql_host'] \
                                                           + '/' + self._configuration['sql_database']
            if self._configuration['sql_view_user'] is not None:
                self._configuration['sql_view_connection_string'] = 'postgresql://' + \
                                                                    self._configuration['sql_view_user'] + ':' + \
                                                                    self._configuration['sql_view_user_key'] + '@' + \
                                                                    self._configuration['sql_host'] + '/' + \
                                                                    self._configuration['sql_database']
        elif self._configuration['sql_type'] == 'MySQL':
            self._configuration['sql_connection_string'] = 'mysql+pymysql://' + self._configuration['user'] + ':' \
                                                           + self._configuration['sql_user_key'] + '@' \
                                                           + self._configuration['sql_host'] \
                                                           + '/' + self._configuration['sql_database']
        else:
            # SQLite is raising ugly error messages when the database directory does not exist.
            if self._configuration['sql_file'] is None:
                self._configuration['sql_file'] = '/'.join([self._configuration['resource_paths'][0], 'sqlite.db'])
            if os.path.dirname(self._configuration['sql_file']) != '' and \
                    not os.path.exists(os.path.dirname(self._configuration['sql_file'])):
                os.makedirs(os.path.dirname(self._configuration['sql_file']))
            self._configuration['sql_connection_string'] = 'sqlite:///' + \
                                                           self._configuration['sql_file'].replace('\\', '/')

        self._database = None
        self._use_local_database = False
        self.logger = setup_logger()

    @property
    def database(self):
        return self._database

    @property
    def login_user(self):
        """
        Get the username of the current user

        Returns:
            str: username
        """
        return self._configuration['user']

    @property
    def resource_paths(self):
        """
        Get the path where the potentials for the individual Hamiltons are located

        Returns:
            list: path of paths
        """
        return self._configuration['resource_paths']

    def __del__(self):
        """
        Close database connection
        """
        self.close_connection()

    def open_connection(self):
        """
        Internal function to open the connection to the database. Only after this function is called the database is
        accessable.
        """
        if self._database is None:
            self._database = DatabaseAccess(self._configuration['sql_connection_string'],
                                            self._configuration['sql_table_name'])

    def switch_to_local_database(self, file_name='pyiron.db', cwd=None):
        if not self._use_local_database:
            if cwd is None and not os.path.isabs(file_name):
                file_name = os.path.join(os.path.abspath(os.path.curdir), file_name)
            elif cwd is not None:
                file_name = os.path.join(cwd, file_name)
            self.close_connection()
            self._database = DatabaseAccess('sqlite:///' + file_name,
                                            self._configuration['sql_table_name'])
            self._use_local_database = True 
        else:
            print('Database is already in local mode!')
            
    def switch_to_central_database(self):
        if self._use_local_database:
            self.close_connection()
            self._database = DatabaseAccess(self._configuration['sql_connection_string'],
                                            self._configuration['sql_table_name'])
            self._use_local_database = False
        else:
            print('Database is already in central mode!')
            
    def switch_to_viewer_mode(self):
        """
        Switch from user mode to viewer mode - if viewer_mode is enable pyiron has read only access to the database.
        """
        if self._configuration['sql_view_connection_string'] is not None:
            if not self._database.viewer_mode:
                self.close_connection()
                self._database = DatabaseAccess(self._configuration['sql_view_connection_string'],
                                                self._configuration['sql_view_table_name'])
                self._database.viewer_mode = True
            else:
                print('Database is already in viewer mode!')
        else:
            print('Viewer Mode is not available on this pyiron installation.')

    def switch_to_user_mode(self):
        """
        Switch from viewer mode to user mode - if viewer_mode is enable pyiron has read only access to the database.
        """
        if self._configuration['sql_view_connection_string'] is not None:
            if self._database.viewer_mode:
                self.close_connection()
                self._database = DatabaseAccess(self._configuration['sql_connection_string'],
                                                self._configuration['sql_table_name'])
                self._database.viewer_mode = True
            else:
                print('Database is already in user mode!')
        else:
            print('Viewer Mode is not available on this pyiron installation.')

    def close_connection(self):
        """
        Internal function to close the connection to the database.
        """
        if hasattr(self, '_database') and self._database is not None:
            self._database.conn.close()
            self._database = None

    def top_path(self, full_path):
        """
        Validated that the full_path is a sub directory of one of the pyrion environments loaded.

        Args:
            full_path (str): path

        Returns:
            str: path
        """
        if full_path[-1] != '/':
            full_path += '/'
        for path in self._configuration['project_paths']:
            if path in full_path:
                return path
        raise ValueError('the current path {0} is not included in the .pyiron configuration. {1}'.format(full_path, self._configuration['project_paths']))

    # private functions
    def _config_parse_file(self, config_file):
        """
        Read section in configuration file and return a dictionary with the corresponding parameters.

        Args:
            config_file(str): confi file to parse

        Returns:
            dict: dictionary with the environment configuration
        """
        # load config parser - depending on Python version
        if sys.version_info.major == 2:
            parser = ConfigParser()
        else:
            parser = ConfigParser(inline_comment_prefixes=(';',))

        # read config
        parser.read(config_file)

        # load first section or default section [DEFAULT]
        if len(parser.sections()) > 0:
            section = parser.sections()[0]
        else:
            section = 'DEFAULT'

        # identify SQL type
        if parser.has_option(section, "TYPE"):
            self._configuration['sql_type'] = parser.get(section, "TYPE")

        # read variables
        if parser.has_option(section, "PROJECT_PATHS"):
            self._configuration['project_paths'] = [convert_path(c.strip())
                                                    for c in parser.get(section, "PROJECT_PATHS").split(",")]
        elif parser.has_option(section, "TOP_LEVEL_DIRS"):  # for backwards compatibility
            self._configuration['project_paths'] = [convert_path(c.strip())
                                                    for c in parser.get(section, "TOP_LEVEL_DIRS").split(",")]
        else:
            ValueError('No project path identified!')

        if parser.has_option(section, 'RESOURCE_PATHS'):
            self._configuration['resource_paths'] = [convert_path(c.strip())
                                                     for c in parser.get(section, 'RESOURCE_PATHS').split(",")]
        if self._configuration['sql_type'] in ['Postgres', 'MySQL']:
            if parser.has_option(section, "USER") & parser.has_option(section, "PASSWD") \
                    & parser.has_option(section, "HOST") & parser.has_option(section, "NAME"):
                self._configuration['user'] = parser.get(section, "USER")
                self._configuration['sql_user_key'] = parser.get(section, "PASSWD")
                self._configuration['sql_host'] = parser.get(section, "HOST")
                self._configuration['sql_database'] = parser.get(section, "NAME")
                self._configuration['sql_file'] = None
            else:
                raise ValueError('If type Postgres or MySQL are selected the options USER, PASSWD, HOST and NAME are'
                                 'required in the configuration file.')
            if parser.has_option(section, "VIEWERUSER") & parser.has_option(section, "VIEWERPASSWD") \
                    & parser.has_option(section, "VIEWER_TABLE"):
                self._configuration['sql_view_table_name'] = parser.get(section, "VIEWER_TABLE")
                self._configuration['sql_view_user'] = parser.get(section, "VIEWERUSER")
                self._configuration['sql_view_user_key'] = parser.get(section, "VIEWERPASSWD")
        elif self._configuration['sql_type'] == 'SQLalchemy':
            self._configuration['sql_connection_string'] = parser.get(section, "CONNECTION")
        else:  # finally we assume an SQLite connection
            if parser.has_option(section, "FILE"):
                self._configuration['sql_file'] = parser.get(section, "FILE").replace('\\', '/')
            if parser.has_option(section, "DATABASE_FILE"):
                self._configuration['sql_file'] = parser.get(section, "DATABASE_FILE").replace('\\', '/')
        if parser.has_option(section, "JOB_TABLE"):
            self._configuration['sql_table_name'] = parser.get(section, "JOB_TABLE")


def convert_path(path):
    if not (sys.version_info.major < 3 and os.name == 'nt'):
        return Path(path).expanduser().resolve().absolute().as_posix()
    else:
        return os.path.abspath(os.path.normpath(os.path.expanduser(path))).replace('\\', '/')
