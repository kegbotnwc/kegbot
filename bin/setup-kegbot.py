#!/usr/bin/env python
#
# Copyright 2013 Mike Wakerly <opensource@hoho.com>
#
# This file is part of the Pykeg package of the Kegbot project.
# For more information on Pykeg or Kegbot, see http://kegbot.org/
#
# Pykeg is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 2 of the License, or
# (at your option) any later version.
#
# Pykeg is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Pykeg.  If not, see <http://www.gnu.org/licenses/>.

"""Kegbot Server setup program.

This program is intended for configuring a fresh install of Kegbot.  It cannot
be used on an active Kegbot install.
"""

from __future__ import absolute_import

import os
import sys
import gflags
import getpass
import pprint
import random
import subprocess

import pytz
from kegbot.util import app

from pykeg import __version__ as VERSION
from pykeg.core import kb_common

gflags.DEFINE_boolean('use_existing', True,
    'Bootstrap default values from existing local_settings, if available.')

gflags.DEFINE_boolean('interactive', True,
    'Run in interactive mode.')

gflags.DEFINE_boolean('replace_settings', False,
    'Overwrite target settings file, rather than abort, if it already exists.')

gflags.DEFINE_boolean('replace_data', False,
    'Do not abort if data_root already exists.  WARNING: The contents of '
    '<data_root>/static/, if any, will be erased and replaced with static '
    'Kegbot files.')

gflags.DEFINE_string('settings_dir', '~/.kegbot',
    'Settings file directory.  ')

gflags.DEFINE_string('data_root', '~/kegbot-data',
    'Data root for Kegbot.')

gflags.DEFINE_string('db_type', 'sqlite',
    'One of: mysql, sqlite.')

gflags.DEFINE_string('mysql_user', 'root',
    'MySQL username.  Ignored if using sqlite.')

gflags.DEFINE_string('mysql_password', '',
    'MySQL password.  Ignored if using sqlite.')

gflags.DEFINE_string('mysql_database', 'kegbot',
    'MySQL database name.  Ignored if using sqlite.')

gflags.DEFINE_string('sqlite_filename', 'kegbot.sqlite',
    'File name for the Kegbot sqlite database within `data_root`.  Ignored if using MySQL.')

gflags.DEFINE_string('timezone', 'America/Los_Angeles',
    'Default time zone.')

gflags.DEFINE_string('use_memcached', True,
    'Configure Kegbot to use memcached. ')

FLAGS = gflags.FLAGS

SETTINGS_TEMPLATE = """# Kegbot local settings.
# Auto-generated by %s version %s.
# Safe to edit by hand. See http://kegbot.org/docs/server/ for more info.

# NEVER set DEBUG to `True` in production.
DEBUG = True
TEMPLATE_DEBUG = DEBUG

""" % (sys.argv[0], VERSION)

# Context values which will be copied to the output settings.
SETTINGS_NAMES = (
  'DATABASES',
  'KEGBOT_ROOT',
  'MEDIA_ROOT',
  'STATIC_ROOT',
  'TIME_ZONE',
  'CACHES',
  'SECRET_KEY',
)

class FatalError(Exception):
  """Cannot proceed."""

def load_existing():
  """Attempts to load the existing local_settings module.

  Returns:
    Loaded module, or None if not loadable.
  """
  try:
    from pykeg.core import importhacks
    existing = __import__('local_settings')
    return existing
  except ImportError:
    return None

def trim(docstring):
  """Docstring trimming function, per PEP 257."""
  if not docstring:
    return ''
  # Convert tabs to spaces (following the normal Python rules)
  # and split into a list of lines:
  lines = docstring.expandtabs().splitlines()
  # Determine minimum indentation (first line doesn't count):
  indent = sys.maxint
  for line in lines[1:]:
    stripped = line.lstrip()
    if stripped:
      indent = min(indent, len(line) - len(stripped))
  # Remove indentation (first line is special):
  trimmed = [lines[0].strip()]
  if indent < sys.maxint:
    for line in lines[1:]:
      trimmed.append(line[indent:].rstrip())
  # Strip off trailing and leading blank lines:
  while trimmed and not trimmed[-1]:
    trimmed.pop()
  while trimmed and not trimmed[0]:
    trimmed.pop(0)
  # Return a single string:
  return '\n'.join(trimmed)

### Setup steps

# These define the actual prompts taken during setup.

class SetupStep(object):
  """A step in Kegbot server configuration.

  The base class has no user interface (flags or prompt); see
  ConfigurationSetupStep for that.
  """
  def get_docs(self):
    """Returns the prompt description text."""
    return trim(self.__doc__)

  def get(self, interactive, ctx):
    if interactive:
      docs = self.get_docs()
      print '-'*80
      print '\n'.join(docs.splitlines()[2:])
      print ''
      print ''

  def validate(self, ctx):
    """Validates user input.

    Args:
      ctx: context
    Raises:
      ValueError: on illegal value
    """
    pass

  def save(self, ctx):
    """Performs the action associated with the step, saving any needed values in
    `ctx`"""
    pass


class ConfigurationSetupStep(SetupStep):
  """A SetupStep that gets and/or applies some configuration value."""
  FLAG = None
  CHOICES = []

  def __init__(self):
    super(ConfigurationSetupStep, self).__init__()
    self.value = None

  def do_prompt(self, prompt, choices=[], default=None):
    """Prompts for and returns a value."""
    choices_text = ''
    if choices:
      choices_text = ' (%s)' % ', '.join(choices)

    default_text = ''
    if default is not None:
      default_text = ' [%s]' % default

    prompt_text = '%s%s%s: ' % (prompt, choices_text, default_text)

    value = raw_input(prompt_text)
    if value == '':
      return default
    return value

  def get_default(self, ctx):
    return self.get_from_flag(ctx)

  def get_from_prompt(self, ctx):
    docs = self.get_docs()
    return self.do_prompt(docs.splitlines()[0], self.CHOICES,
        self.get_default(ctx))

  def get_from_flag(self, ctx):
    if self.FLAG:
      return getattr(FLAGS, self.FLAG)
    return None

  def get(self, interactive, ctx):
    super(ConfigurationSetupStep, self).get(interactive, ctx)
    if interactive:
      ret = self.get_from_prompt(ctx)
    else:
      ret = self.get_from_flag(ctx)
    self.value = ret

  def validate(self, ctx):
    if self.CHOICES and self.value not in self.CHOICES:
      raise ValueError('Value must be one of: %s' % ', '.join(self.CHOICES))
    super(ConfigurationSetupStep, self).validate(ctx)

  def save(self, ctx):
    pass

### Main Steps

class RequiredLibraries(SetupStep):
  def validate(self, ctx):
    try:
        from PIL import Image, ImageColor, ImageChops, ImageEnhance, ImageFile, \
                ImageFilter, ImageDraw, ImageStat
    except ImportError:
        try:
            import Image
            import ImageColor
            import ImageChops
            import ImageEnhance
            import ImageFile
            import ImageFilter
            import ImageDraw
            import ImageStat
        except ImportError:
            raise FatalError('Could not locate Python Imaging Library, '
                'please install it ("pip install pillow" or "apt-get install python-imaging")')


class SettingsDir(ConfigurationSetupStep):
  """Select the settings file location.

  Kegbot's master settings file for this system (local_settings.py) should live
  in one of two places on the filesystem:

    ~/.kegbot/     (local to this user, recommended)
    /etc/kegbot/   (global to all users, requires root access)

  If in doubt, use the default.
  """
  FLAG = 'settings_dir'
  CHOICES = ('~/.kegbot', '/etc/kegbot')

  def validate(self, ctx):
    self.value = os.path.expanduser(self.value)
    if os.path.exists(self.value) and not os.path.isdir(self.value):
      raise ValueError('Settings dir "%s" exists and is a file.' % self.value)
    ctx['SETTINGS_DIR'] = self.value
    if 'SECRET_KEY' not in ctx:
      ctx['SECRET_KEY'] = ''.join([random.choice('abcdefghijklmnopqrstuvwxyz0123456789!@#$%^&*(-_=+)') for i in range(50)])

  def save(self, ctx):
    if not os.path.exists(self.value):
      try:
        os.makedirs(self.value)
      except OSError, e:
        raise FatalError("Couldn't create settings dir '%s': %s" % (self.value, e))


class KegbotDataRoot(ConfigurationSetupStep):
  """Path to Kegbot's data root.

  This should be a directory on your filesystem where Kegbot will create its
  STATIC_ROOT (static files used by the web server, such as css and java script)
  and MEDIA_ROOT (media uploads like user profile pictures).
  """
  FLAG = 'data_root'

  def validate(self, ctx):
    self.value = os.path.expanduser(self.value)
    if os.path.exists(self.value):
      if os.listdir(self.value):
        if not FLAGS.replace_data:
          raise ValueError('Data root "%s" already exists and is not empty.' % self.value)
    media_root = os.path.join(self.value, 'media')
    static_root = os.path.join(self.value, 'static')
    ctx['KEGBOT_ROOT'] = self.value
    ctx['MEDIA_ROOT'] = media_root
    ctx['STATIC_ROOT'] = static_root
    super(KegbotDataRoot, self).validate(ctx)

  def save(self, ctx):
    static_root = ctx['STATIC_ROOT']
    media_root = ctx['MEDIA_ROOT']
    try:
      os.makedirs(static_root)
      os.makedirs(media_root)
    except OSError, e:
      raise FatalError('Could not create directory "%s": %s' % (self.value, e))


class TimeZone(ConfigurationSetupStep):
  """Time zone for this system.

  The value should be a string time zone name. Examples:
    America/Los_Angeles
    America/Denver
    America/Chicago
    America/New_York
    Australia/ACT
    GMT

  A full list of acceptable names can be found here:
    http://www.postgresql.org/docs/8.1/static/datetime-keywords.html#DATETIME-TIMEZONE-SET-TABLE
  """

  FLAG = 'timezone'

  def validate(self, ctx):
    try:
      tz = pytz.timezone(self.value)
    except pytz.exceptions.UnknownTimeZoneError:
      raise ValueError('Timezone "%s" is not known.')
    ctx['TIME_ZONE'] = self.value


class Memcached(ConfigurationSetupStep):
  """Enable memcached caching layer.

  If memcached is installed and available, Kegbot can use it to perform some
  operations faster.  On Ubuntu, you can install memcached this way:
    sudo apt-get install memcached

  It's generally a good idea to enable this.
  """
  FLAG = 'use_memcached'
  HOST = '127.0.0.1:11211'  # todo: make configurable
  CHOICES = ['yes', 'no']

  def get_default(self, ctx):
    return ('no', 'yes')[super(Memcached, self).get_default(ctx)]

  def validate(self, ctx):
    if self.value == 'yes':
      self.value = True
    if self.value == 'no':
      self.value = False
    if self.value not in (True, False):
      raise ValueError('Please enter "yes" or "no".')

    if not self.value:
      return

    client = None
    try:
      import memcache
      client = memcache.Client([self.HOST])
    except ImportError:
      try:
        import pylibmc
        client = pylibmc.Client([self.HOST])
      except ImportError:
        pass

    if not client:
      raise ValueError('Memcache client library is not installed. '
          '("pip install python-memcached" or "pip install pylibmc")')

    if self.value:
      ctx['CACHES'] = {
          'default': {
            'BACKEND':  'django.core.cache.backends.memcached.MemcachedCache',
            'LOCATION': self.HOST,
          }
      }


class ConfigureDatabase(ConfigurationSetupStep):
  """Select database for Kegbot Server backend.

  Currently only sqlite and MySQL are supported by the setup wizard.
  """
  def get_from_flag(self, ctx):
    self.choice = FLAGS.db_type
    if self.choice == 'sqlite':
      return FLAGS.sqlite_filename
    else:
      return (FLAGS.mysql_user, FLAGS.mysql_password, FLAGS.mysql_database)

  def get_from_prompt(self, ctx):
    self.choice = self.do_prompt('Database type',
        choices=('sqlite', 'mysql'), default=FLAGS.db_type)

    if self.choice == 'sqlite':
      root = ctx['KEGBOT_ROOT']
      return self.do_prompt('SQLite database filename to create in %s' % root,
          default=FLAGS.sqlite_filename)
    else:
      user = self.do_prompt('MySQL user')
      password = getpass.getpass()
      database = self.do_prompt('Database name', default='kegbot')
      return (user, password, database)

  def validate(self, ctx):
    super(ConfigureDatabase, self).validate(ctx)
    if self.choice == 'sqlite':
      root = ctx['KEGBOT_ROOT']
      path = os.path.join(root, self.value)
      if os.path.exists(path):
        raise ValueError('SQLite database file already exists at %s' % path)
    else:
      user, password, database = self.value
      if user == '':
        raise ValueError('Must give a MySQL username')
      elif database == '':
        raise ValueError('Must give a MySQL database name')

    if self.choice == 'sqlite':
      cfg = {
        'default': {
          'ENGINE': 'django.db.backends.sqlite3',
          'NAME': os.path.join(ctx['KEGBOT_ROOT'], self.value),
        }
      }
    else:
      user, password, database = self.value
      cfg = {
        'default': {
          'ENGINE': 'django.db.backends.mysql',
          'NAME': database,
          'USER': user,
          'PASSWORD': password,
          'OPTIONS': {
            'init_command': 'SET storage_engine=INNODB',
          }
        }
      }

    ctx['DATABASES'] = cfg


STEPS = [
    RequiredLibraries(),
    SettingsDir(),
    TimeZone(),
    Memcached(),
    KegbotDataRoot(),
    ConfigureDatabase(),
]


class SetupApp(app.App):
  def _Setup(self):
    app.App._Setup(self)

  def _SetupSignalHandlers(self):
    pass

  def _MainLoop(self):
    steps = STEPS
    ctx = {}

    if FLAGS.interactive:
      self.build_interactive(ctx)
    else:
      self.build(ctx)

    try:
      self.finish_setup(ctx)
    except (ValueError, FatalError), e:
      print 'ERROR: %s' % e
      sys.exit(1)

  def build(self, ctx):
    for step in STEPS:
      try:
        step.get(interactive=False, ctx=ctx)
        step.validate(ctx)
      except (ValueError, FatalError), e:
        print 'ERROR: %s' % e
        sys.exit(1)

  def build_interactive(self, ctx):
    try:
      import readline
    except ImportError:
      pass

    for step in STEPS:
      while not self._do_quit:
        try:
          step.get(interactive=True, ctx=ctx)
          step.validate(ctx)
          print ''
          print ''
          break
        except KeyboardInterrupt, e:
          print ''
          sys.exit(1)
        except FatalError, e:
          print ''
          print 'ERROR: %s' % e
          sys.exit(1)
        except ValueError, e:
          print ''
          print ''
          print ''
          print 'ERROR: %s' % e


  def finish_setup(self, ctx):
    print ''
    print 'Generated configuration:'
    for key in sorted(SETTINGS_NAMES):
      print '  %s = %s' % (key, repr(ctx.get(key)))
    print ''

    for step in STEPS:
      step.save(ctx)

    settings_file = os.path.join(ctx['SETTINGS_DIR'], 'local_settings.py')
    print 'Writing settings to %s ..' % settings_file

    if os.path.exists(settings_file) and not FLAGS.replace_settings:
      raise ValueError('%s exists and --replace_settings was not given.' % settings_file)

    outfd = open(settings_file, 'w+')
    outfd.write(SETTINGS_TEMPLATE)
    for key in SETTINGS_NAMES:
      if key in ctx:
        outfd.write('%s = %s\n\n' % (key, repr(ctx[key])))
    outfd.close()

    print 'Finishing setup ...'
    existing = load_existing()
    if not existing:
      raise ValueError('Could not import local_settings.')

    existing_file = existing.__file__
    if not existing_file.startswith(settings_file):  # py,pyc
      raise ValueError('Imported settings does not match: imported=%s '
          'expected=%s' % (existing_file, settings_file))

    self.run_command('kegbot-admin.py syncdb --all --noinput -v 0')
    self.run_command('kegbot-admin.py migrate --all --fake --noinput -v 0')
    self.run_command('kegbot-admin.py kb_set_defaults --force')

    if FLAGS.interactive:
      try:
        self.run_command('kegbot-admin.py collectstatic')
      except FatalError, e:
        print 'WARNING: Collecting static files failed: %s' % e
        print ''
        print 'Try again with "kegbot-admin.py collectstatic"'
    else:
      self.run_command('kegbot-admin.py collectstatic --noinput')

    print ''
    print 'Done!'
    print ''
    print 'You may now run the dev server:'
    print 'kegbot-admin.py runserver'

  def run_command(self, s, allow_fail=False):
    print 'Running command: %s' % s
    ret = subprocess.call(s.split())
    if ret != 0:
      msg = 'Command returned non-zero exit status (%s)' % ret
      if allow_fail:
        print msg
      else:
        raise FatalError(msg)

if __name__ == '__main__':
  SetupApp.BuildAndRun(name='kegbot-setup')
