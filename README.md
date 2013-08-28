dumpcode
========

[![Build Status](https://travis-ci.org/veatch/dumpcode.png)](https://travis-ci.org/veatch/dumpcode)

Fixtures slow down tests: the django test runner searches for the
specified fixtures and reads them from the filesystem, and it does this
for every test in the test class (search speed is improved in django 1.6).
Often fixtures create objects that are not needed by tests, or are only needed
for a subset of the tests. Replacing fixtures with code
will decrease the runtime of your test suite and will make it easier to make
further improvements to your tests.

Installation and Use
------------------------
Copy dumpcode into your project and add to INSTALLED_APPS.

Run the management command:
`django-admin.py dumpcode fixture_name second_fixture_name`
The command will locate the specified fixtures the same way
loaddata does and then print methods to create the objects found in them.

Paste the methods into your test file and call them from your test class's
setUp method.

Next Steps
------------------------
After removing fixtures, consider further improvements like deleting
creation of objects that aren't needed by your tests, moving creation
of objects that aren't needed by all tests into the test methods that use them, and
simply instantiating objects rather than saving them to the database.
