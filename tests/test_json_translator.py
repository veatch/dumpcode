import mock
from django.db import models

from dumpcode.management.commands.dumpcode import JsonTranslator

class FooModel(models.Model):
    name = models.CharField()

class TestJsonTranslator(object):
    """
    Test JsonTranslator's translation of json to python.
    """

    @mock.patch('dumpcode.management.commands.dumpcode._get_model', FooModel)
    def setup(self):
        self.trans = JsonTranslator('fixture_name')
        json = {"pk": 1, "model": "dumpcode.foomodel", "fields": {"name": "test"}}
        self.trans.translate_object(json)

    def test_import_statements(self):
        """ test generation of import statement """
        assert (self.trans.import_statements ==
            ['from dumpcode.tests.test_json_translator import FooModel'])

    def test_object_setup_statements(self):
        """ test generation of create statement """
        assert (self.trans.object_setup_statements ==
            ["FooModel.objects.create(**{'id': 1, 'name': u'test'})"])
