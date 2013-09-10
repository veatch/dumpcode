import datetime
import decimal
import gzip
import os
import zipfile

from django.conf import settings
from django.core.management.base import BaseCommand
from django.core.serializers import base
from django.db import DEFAULT_DB_ALIAS, models
from django.utils import simplejson
from django.utils.encoding import smart_unicode
from django.utils.itercompat import product

try:
    import bz2
    has_bz2 = True
except ImportError:
    has_bz2 = False

class SingleZipReader(zipfile.ZipFile):
    def __init__(self, *args, **kwargs):
        zipfile.ZipFile.__init__(self, *args, **kwargs)
        if len(self.namelist()) != 1:
            raise ValueError("Zip-compressed fixtures must contain one file.")

    def read(self):
        return zipfile.ZipFile.read(self, self.namelist()[0])

compression_types = {
    None: open,
    'gz': gzip.GzipFile,
    'zip': SingleZipReader
}
if has_bz2:
    compression_types['bz2'] = bz2.BZ2File

INDENT = '    '


class Command(BaseCommand):
    """
    Usage: django-admin.py dumpcode fixture.json
    This will read the given fixture, translate json representation of objects into
    python, and print a method that will create all objects from fixture.
    Based on loaddata management command (django/core/management/commands/loaddata.py)
    """
    help = ''
    def handle(self, *fixture_labels, **options):

        if not len(fixture_labels):
            self.stderr.write(
                "No database fixture specified. Please provide the path of at least one fixture in the command line.\n"
            )
            return

        self.verbosity = int(options.get('verbosity'))

        for fixture_label in fixture_labels:
            translator = JsonTranslator(fixture_label)
            self.setup_name_compression_dir(fixture_label.split('.'))

            fixture_files = self.find_fixtures(fixture_label, self.fixture_dirs)

            if not fixture_files:
                self.stderr.write("\nCould not find fixture: %s.\n" % fixture_label)

            for full_path, compression_format in fixture_files:
                try:
                    fixture = open_fixture(full_path, compression_format)
                except IOError:
                    if self.verbosity >= 2:
                        self.stdout.write("Error opening fixture %s.\n" % full_path)
                else:
                    for obj_json in simplejson.load(fixture):
                        translator.translate_object(obj_json)
                finally:
                    fixture.close()
                    translator.out()

    def find_fixtures(self, fixture_label, fixture_dirs):
        """
        Search for fixture_label in fixture_dirs. Returns list of tuples.
        In each tuple first element is fixture's full path, second element
        is compression format.
        """
        fixtures = []
        for fixture_dir in fixture_dirs:
            if self.verbosity >= 2:
                self.stdout.write("Checking %s for fixtures...\n" % humanize(fixture_dir))

            label_found = False
            for combo in product(['json'], self.compression_formats):
                format, compression_format = combo
                file_name = '.'.join(
                    p for p in [
                        self.fixture_name, format, compression_format
                    ]
                    if p
                )

                if self.verbosity >= 3:
                    self.stdout.write("Trying %s for %s fixture '%s'...\n" % \
                        (humanize(fixture_dir), file_name, self.fixture_name))
                full_path = os.path.join(fixture_dir, file_name)
                try:
                    fixture = open_fixture(full_path, compression_format)
                except IOError:
                    if self.verbosity >= 2:
                        self.stdout.write("No %s fixture '%s' in %s.\n" % \
                            (format, self.fixture_name, humanize(fixture_dir)))
                else:
                    try:
                        if label_found:
                            self.stderr.write("Multiple fixtures named '%s' in %s. Aborting.\n" %
                                (self.fixture_name, humanize(fixture_dir)))
                            return

                        fixtures.append((full_path, compression_format))

                        if self.verbosity >= 2:
                            self.stdout.write("Installing %s fixture '%s' from %s.\n" % \
                                (format, self.fixture_name, humanize(fixture_dir)))


                        label_found = True
                    finally:
                        fixture.close()

        return fixtures

    def setup_name_compression_dir(self, parts):
        """
        Given parts of fixture label, set compression_formats, fixture_name,
        and fixture_dirs.
        """
        app_module_paths = []

        for app in models.get_apps():
            if hasattr(app, '__path__'):
                # It's a 'models/' subpackage
                for path in app.__path__:
                    app_module_paths.append(path)
            else:
                # It's a models.py module
                app_module_paths.append(app.__file__)

        app_fixtures = [os.path.join(os.path.dirname(path), 'fixtures') for path in app_module_paths]

        if len(parts) > 1 and parts[-1] in compression_types:
            self.compression_formats = [parts[-1]]
            parts = parts[:-1]
        else:
            self.compression_formats = compression_types.keys()

        if len(parts) == 1:
            self.fixture_name = parts[0]
        else:
            self.fixture_name, format = '.'.join(parts[:-1]), parts[-1]

        if os.path.isabs(self.fixture_name):
            self.fixture_dirs = [self.fixture_name]
        else:
            self.fixture_dirs = app_fixtures + list(settings.FIXTURE_DIRS) + ['']

class JsonTranslator(object):
    """
    For a given fixture, accepts json representations of objects and translates to python.
    Prints a method with necessary imports and python creation statements.
    The translate_object method is based on Deserializer in django/core/serializers/python.py
    """
    def __init__(self, fixture_name):
        self.import_statements = []
        self.object_setup_statements = []
        self.db = DEFAULT_DB_ALIAS
        self.fixture_name = fixture_name

    def translate_object(self, obj_json):
        """
        Given json representation of object, make python strings to create object.
        Add import string for object's model to import_statements (if it's not
        already there), add string to create object to object_setup_statements,
        and add strings to create many-to-many relations to object_setup_statements.
        Based on Deserializer in django/core/serializers/python.py
        """
        Model = _get_model(obj_json["model"])

        data = {Model._meta.pk.attname : Model._meta.pk.to_python(obj_json["pk"])}
        m2m_data = {}
        self.add_import('from %s import %s' % (Model.__module__, Model._meta.object_name))

        # Handle each field
        for (field_name, field_value) in obj_json["fields"].iteritems():
            if isinstance(field_value, str):
                field_value = smart_unicode(field_value, strings_only=True)

            field = Model._meta.get_field(field_name)

            # Handle M2M relations
            if field.rel and isinstance(field.rel, models.ManyToManyRel):
                if hasattr(field.rel.to._default_manager, 'get_by_natural_key'):
                    def m2m_convert(value):
                        if hasattr(value, '__iter__'):
                            return field.rel.to._default_manager.db_manager(self.db).get_by_natural_key(*value).pk
                        else:
                            return smart_unicode(field.rel.to._meta.pk.to_python(value))
                else:
                    m2m_convert = lambda v: smart_unicode(field.rel.to._meta.pk.to_python(v))
                m2m_data[field.name] = [m2m_convert(pk) for pk in field_value]

            # Handle FK fields
            elif field.rel and isinstance(field.rel, models.ManyToOneRel):
                if field_value is not None:
                    if hasattr(field.rel.to._default_manager, 'get_by_natural_key'):
                        if hasattr(field_value, '__iter__'):
                            obj = field.rel.to._default_manager.db_manager(self.db).get_by_natural_key(*field_value)
                            value = getattr(obj, field.rel.field_name)
                            # If this is a natural foreign key to an object that
                            # has a FK/O2O as the foreign key, use the FK value
                            if field.rel.to._meta.pk.rel:
                                value = value.pk
                        else:
                            value = field.rel.to._meta.get_field(field.rel.field_name).to_python(field_value)
                        data[field.attname] = value
                    else:
                        data[field.attname] = field.rel.to._meta.get_field(field.rel.field_name).to_python(field_value)
                else:
                    data[field.attname] = None

            # Handle all other fields
            else:
                python_field = field.to_python(field_value)
                data[field.name] = python_field
                self.add_field_import(python_field)

        add_m2m = ['getattr(obj, "%s").add(*%s)' % (k, list(v)) for k, v in m2m_data.items() if v]
        obj_str = ''
        if add_m2m:
            obj_str = 'obj = '

        self.object_setup_statements.append('%s%s.objects.create(**%s)' % (obj_str, Model._meta.object_name, data))
        if add_m2m:
            self.object_setup_statements.extend(add_m2m)

    def out(self):
        """
        Print out python strings made by translate_object method as a self-contained method.
        """
        print
        print self.get_method_name()
        for imprt in self.import_statements:
            print '%s%s' % (INDENT, imprt)
        print
        for c in self.object_setup_statements:
            print '%s%s' % (INDENT, c)

    def add_import(self, imprt):
        if imprt not in self.import_statements:
            self.import_statements.append(imprt)

    def add_field_import(self, field):
        if isinstance(field, datetime.datetime) or isinstance(field, datetime.date) or isinstance(field, datetime.time):
            self.add_import('import datetime')
        elif isinstance(field, decimal.Decimal):
            self.add_import('from decimal import Decimal')

    def get_method_name(self):
        return 'def create_%s_objects():' % self.fixture_name.replace('.', '_')


humanize = lambda dirname: "'%s'" % dirname if dirname else 'absolute path'

def open_fixture(fixture, compression_format):
    open_method = compression_types[compression_format]
    return open_method(fixture, 'r')

def _get_model(model_identifier):
    """
    Helper to look up a model from an "app_label.module_name" string.
    """
    try:
        Model = models.get_model(*model_identifier.split("."))
    except TypeError:
        Model = None
    if Model is None:
        raise base.DeserializationError(u"Invalid model identifier: '%s'" % model_identifier)
    return Model
