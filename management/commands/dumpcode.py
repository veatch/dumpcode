import gzip
import os
import sys
import traceback
import zipfile

from django.conf import settings
from django.core import serializers
from django.core.management.base import BaseCommand
from django.core.management.color import no_style
from django.core.serializers import base
from django.db import DEFAULT_DB_ALIAS, models
from django.utils import simplejson
from django.utils.encoding import smart_unicode

try:
    import bz2
    has_bz2 = True
except ImportError:
    has_bz2 = False

INDENT = '    '

class Command(BaseCommand):
    """
    Usage: django-admin.py dumpcode fixture.json
    This will read fixture.json, translate json representation of objects into
    python to create those objects, and print a method with the necessary imports
    and python creation statements.
    """
    def handle(self, *fixture_labels, **options):
        using = options.get('database')

        self.style = no_style()

        if not len(fixture_labels):
            self.stderr.write(
                self.style.ERROR("No database fixture specified. Please provide the path of at least one fixture in the command line.\n")
            )
            return

        verbosity = int(options.get('verbosity'))
        show_traceback = options.get('traceback')

        # Keep a count of the installed objects and fixtures
        fixture_count = 0
        loaded_object_count = 0
        fixture_object_count = 0

        humanize = lambda dirname: "'%s'" % dirname if dirname else 'absolute path'

        class SingleZipReader(zipfile.ZipFile):
            def __init__(self, *args, **kwargs):
                zipfile.ZipFile.__init__(self, *args, **kwargs)
                if settings.DEBUG:
                    assert len(self.namelist()) == 1, "Zip-compressed fixtures must contain only one file."
            def read(self):
                return zipfile.ZipFile.read(self, self.namelist()[0])

        compression_types = {
            None:   open,
            #'gz':   gzip.GzipFile,
            #'zip':  SingleZipReader
        }
        #if has_bz2:
            #compression_types['bz2'] = bz2.BZ2File

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

        try:
            for fixture_label in fixture_labels:
                dumper = CodeDumper(fixture_label)
                parts = fixture_label.split('.')

                if len(parts) > 1 and parts[-1] in compression_types:
                    compression_formats = [parts[-1]]
                    parts = parts[:-1]
                else:
                    compression_formats = compression_types.keys()

                if len(parts) == 1:
                    fixture_name = parts[0]
                    formats = serializers.get_public_serializer_formats()
                else:
                    fixture_name, format = '.'.join(parts[:-1]), parts[-1]
                    if format in serializers.get_public_serializer_formats():
                        formats = [format]
                    else:
                        formats = []

                if formats:
                    if verbosity >= 2:
                        self.stdout.write("Loading '%s' fixtures...\n" % fixture_name)
                else:
                    self.stderr.write(
                        self.style.ERROR("Problem installing fixture '%s': %s is not a known serialization format.\n" %
                            (fixture_name, format)))
                    return

                if os.path.isabs(fixture_name):
                    fixture_dirs = [fixture_name]
                else:
                    fixture_dirs = app_fixtures + list(settings.FIXTURE_DIRS) + ['']

                for fixture_dir in fixture_dirs:
                    if verbosity >= 2:
                        self.stdout.write("Checking %s for fixtures...\n" % humanize(fixture_dir))

                    label_found = False
                    for combo in [(None, 'json', None)]:
                        database, format, compression_format = combo
                        file_name = '.'.join(
                            p for p in [
                                fixture_name, database, format, compression_format
                            ]
                            if p
                        )

                        if verbosity >= 3:
                            self.stdout.write("Trying %s for %s fixture '%s'...\n" % \
                                (humanize(fixture_dir), file_name, fixture_name))
                        full_path = os.path.join(fixture_dir, file_name)
                        open_method = compression_types[compression_format]
                        try:
                            fixture = open_method(full_path, 'r')
                        except IOError:
                            if verbosity >= 2:
                                self.stdout.write("No %s fixture '%s' in %s.\n" % \
                                    (format, fixture_name, humanize(fixture_dir)))
                        else:
                            try:
                                if label_found:
                                    self.stderr.write(self.style.ERROR("Multiple fixtures named '%s' in %s. Aborting.\n" %
                                        (fixture_name, humanize(fixture_dir))))
                                    return

                                fixture_count += 1
                                objects_in_fixture = 0
                                loaded_objects_in_fixture = 0
                                if verbosity >= 2:
                                    self.stdout.write("Installing %s fixture '%s' from %s.\n" % \
                                        (format, fixture_name, humanize(fixture_dir)))

                                # python/dj shell, invoke directly so registry isn't issue
                                #json_d = serializers.get_deserializer('json')

                                # just like serializers.python.Deserializer, but after Model:

                                for obj_json in simplejson.load(fixture):
                                    objects_in_fixture += 1
                                    dumper.dump(obj_json)

                                loaded_object_count += loaded_objects_in_fixture
                                fixture_object_count += objects_in_fixture
                                label_found = True
                            finally:
                                fixture.close()
                                dumper.out()

                            # If the fixture we loaded contains 0 objects, assume that an
                            # error was encountered during fixture loading.
                            if objects_in_fixture == 0:
                                self.stderr.write(
                                    self.style.ERROR("No fixture data found for '%s'. (File format may be invalid.)\n" %
                                        (fixture_name)))
                                return

        except (SystemExit, KeyboardInterrupt):
            raise
        except Exception:
            if show_traceback:
                traceback.print_exc()
            else:
                self.stderr.write(
                    self.style.ERROR("Problem installing fixture '%s': %s\n" %
                         (full_path, ''.join(traceback.format_exception(sys.exc_type,
                             sys.exc_value, sys.exc_traceback)))))
            return


class CodeDumper(object):
    """
    For a given fixture, accepts json representations of objects and translates to python.
    Prints a method with necessary imports and python creation statements.
    """
    def __init__(self, fixture_name=None):
        self.imports = []
        self.code = []
        self.db = DEFAULT_DB_ALIAS
        self.fixture_name = ''
        if fixture_name:
            self.fixture_name = fixture_name

    # todo: rename this so it's clearer that one object is being dealt with
    def dump(self, obj_json):
        Model = _get_model(obj_json["model"])
        data = {Model._meta.pk.attname : Model._meta.pk.to_python(obj_json["pk"])}
        m2m_data = {}
        imprt = 'from %s import %s' % (Model.__module__, Model._meta.object_name)
        if imprt not in self.imports:
            self.imports.append(imprt)
        #populate kwargs with dict (no m2m or fks)
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
                data[field.name] = field.to_python(field_value)

        add_m2m = ['getattr(obj, "%s").add(*%s)' % (k, list(v)) for k, v in m2m_data.items() if v]
        obj_str = ''
        if add_m2m:
            obj_str = 'obj = '

        self.code.append('%s%s.objects.create(**%s)' % (obj_str, Model._meta.object_name, data))
        if add_m2m:
            self.code.extend(add_m2m)
            #self.code.append('obj.save()')

    def out(self):
        print
        print 'def create_%s_objects():' % self.fixture_name
        for imprt in self.imports:
            print '%s%s' % (INDENT, imprt)
        print
        for c in self.code:
            print '%s%s' % (INDENT, c)

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
