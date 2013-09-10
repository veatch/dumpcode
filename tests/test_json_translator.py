import mock
from django.db import models

from dumpcode.management.commands.dumpcode import JsonTranslator

class FooModel(models.Model):
    name = models.CharField()

class DateTimeModel(models.Model):
    time = models.DateTimeField()

class DateModel(models.Model):
    time = models.DateField()

class DecimalModel(models.Model):
    longitude = models.DecimalField()

class TimeModel(models.Model):
    time = models.TimeField()

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

def test_get_method_name():
    """ test that filename with extension is handled correctly """
    trans = JsonTranslator('fixture.json')
    assert trans.get_method_name() == 'def create_fixture_json_objects():'

class TestFieldImports(object):
    @mock.patch('dumpcode.management.commands.dumpcode._get_model', DateTimeModel)
    def test_datetime_field(self):
        trans = JsonTranslator('fixture_name')
        json = {"pk": 1, "model": "dumpcode.datetimemodel", "fields": {"time": "2013-09-09 11:48:00"}}
        trans.translate_object(json)
        assert 'import datetime' in trans.import_statements
        assert (trans.object_setup_statements ==
            ["DateTimeModel.objects.create(**{'id': 1, 'time': datetime.datetime(2013, 9, 9, 11, 48)})"])

    @mock.patch('dumpcode.management.commands.dumpcode._get_model', DateModel)
    def test_date_field(self):
        trans = JsonTranslator('fixture_name')
        json = {"pk": 1, "model": "dumpcode.datemodel", "fields": {"time": "2013-09-09"}}
        trans.translate_object(json)
        assert 'import datetime' in trans.import_statements

    @mock.patch('dumpcode.management.commands.dumpcode._get_model', TimeModel)
    def test_time_field(self):
        trans = JsonTranslator('fixture_name')
        json = {"pk": 1, "model": "dumpcode.timemodel", "fields": {"time": "11:48:00"}}
        trans.translate_object(json)
        assert 'import datetime' in trans.import_statements

    @mock.patch('dumpcode.management.commands.dumpcode._get_model', DecimalModel)
    def test_decimal_field(self):
        trans = JsonTranslator('fixture_name')
        json = {"pk": 1, "model": "dumpcode.decimalmodel", "fields": {"longitude": "-84.346082"}}
        trans.translate_object(json)
        assert 'from decimal import Decimal' in trans.import_statements
