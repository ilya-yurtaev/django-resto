import datetime
import logging
import os
import os.path
import shutil
import StringIO
import urllib2

from django.conf import settings
from django.core.files.base import ContentFile
from django.utils import unittest

from ..storage import DistributedStorage, HybridStorage, UnexpectedStatusCode
from .http_server import HttpServerTestCaseMixin, ExtraHttpServerTestCaseMixin


class StorageUtilitiesMixin(HttpServerTestCaseMixin):

    def setUp(self):
        super(StorageUtilitiesMixin, self).setUp()
        self.log = StringIO.StringIO()
        self.logger = logging.getLogger('django_dust.storage')
        self.handler = logging.StreamHandler(self.log)
        self.logger.addHandler(self.handler)
        hosts = ['%s:%d' % (self.host, self.port)]
        self.storage = self.storage_class(hosts=hosts)
        if self.use_fs:
            os.makedirs(settings.MEDIA_ROOT)

    def tearDown(self):
        super(StorageUtilitiesMixin, self).tearDown()
        if self.use_fs:
            shutil.rmtree(settings.MEDIA_ROOT)

    def get_log(self):
        self.handler.flush()
        return self.log.getvalue()

    def has_file(self, name):
        return self.http_server.has_file(name)

    def get_file(self, name):
        return self.http_server.get_file(name)

    def create_file(self, name, content):
        self.http_server.create_file(name, content)
        if self.use_fs:
            filename = os.path.join(settings.MEDIA_ROOT, name)
            if not os.path.isdir(os.path.dirname(filename)):
                os.makedirs(os.path.dirname(filename))
            with open(filename, 'wb') as f:
                f.write(content)

    def delete_file(self, name):
        self.http_server.delete_file(name)
        if self.use_fs:
            filename = os.path.join(settings.MEDIA_ROOT, name)
            os.unlink(filename)


class StorageUtilitiesWithTwoServersMixin(
        ExtraHttpServerTestCaseMixin, StorageUtilitiesMixin):

    def setUp(self):
        super(StorageUtilitiesWithTwoServersMixin, self).setUp()
        hosts = ['%s:%d' % (self.host, self.port + 1 - i) for i in range(2)]
        self.storage = self.storage_class(hosts=hosts)

    def create_file(self, name, content):
        self.alt_http_server.create_file(name, content)
        super(StorageUtilitiesWithTwoServersMixin, self).create_file(name, content)

    def delete_file(self, name):
        self.alt_http_server.delete_file(name)
        super(StorageUtilitiesWithTwoServersMixin, self).delete_file(name)


class StorageTestCaseMixin(object):

    # See http://docs.djangoproject.com/en/dev/ref/files/storage/
    # for the full storage API.
    # See http://docs.djangoproject.com/en/dev/howto/custom-file-storage/
    # for a list of which methods a custom storage class must implement.

    def test_accessed_time(self):
        self.create_file('test.txt', 'test')
        self.assertIsInstance(self.storage.accessed_time('test.txt'), datetime.datetime)

    def test_accessed_time_non_existing(self):
        self.assertRaises(EnvironmentError, self.storage.accessed_time, 'test.txt')

    def test_created_time(self):
        self.create_file('test.txt', 'test')
        self.assertIsInstance(self.storage.created_time('test.txt'), datetime.datetime)

    def test_created_time_non_existing(self):
        self.assertRaises(EnvironmentError, self.storage.created_time, 'test.txt')

    def test_delete(self):
        self.create_file('test.txt', 'test')
        self.assertTrue(self.has_file('test.txt'))
        self.storage.delete('test.txt')
        self.assertFalse(self.has_file('test.txt'))

    def test_delete_non_existing(self):
        # by design, this doesn't raise an exception, but it logs a warning
        self.storage.delete('test.txt')
        self.assertFalse(self.has_file('test.txt'))
        self.assertIn("DELETE on missing file", self.get_log())

    def test_delete_readonly(self):
        self.create_file('test.txt', 'test')
        self.http_server.readonly = True
        self.assertRaises(urllib2.HTTPError, self.storage.delete, 'test.txt')
        self.assertIn("Failed to delete", self.get_log())

    def test_delete_dilettante(self):
        self.http_server.override_code = 202
        self.create_file('test.txt', 'test')
        self.assertRaises(UnexpectedStatusCode, self.storage.delete, 'test.txt')
        self.assertIn("Failed to delete", self.get_log())

    def test_exists(self):
        self.create_file('test.txt', 'test')
        self.assertTrue(self.storage.exists('test.txt'))
        self.delete_file('test.txt')
        self.assertFalse(self.storage.exists('test.txt'))

    def test_get_available_name(self):
        self.assertEqual(self.storage.get_available_name('test.txt'), 'test.txt')

    def test_get_available_name_existing(self):
        self.create_file('test.txt', 'test')
        self.assertEqual(self.storage.get_available_name('test.txt'), 'test_1.txt')

    def test_get_valid_name(self):
        self.assertEqual(self.storage.get_valid_name('test.txt'), 'test.txt')

    def test_listdir(self):
        self.create_file('test/foo.txt', 'foo')
        self.create_file('test/bar.txt', 'bar')
        self.create_file('test/baz/quux.txt', 'quux')
        listing = self.storage.listdir('test')
        self.assertEqual(set(listing[0]), set(['baz']))
        self.assertEqual(set(listing[1]), set(['foo.txt', 'bar.txt']))

    def test_listdir_non_existing(self):
        self.assertRaises(EnvironmentError, self.storage.listdir, 'test')

    def test_modified_time(self):
        self.create_file('test.txt', 'test')
        self.assertIsInstance(self.storage.modified_time('test.txt'), datetime.datetime)

    def test_modified_time_non_existing(self):
        self.assertRaises(EnvironmentError, self.storage.modified_time, 'test.txt')

    def test_open(self):
        self.create_file('test.txt', 'test')
        with self.storage.open('test.txt') as f:
            self.assertEqual(f.read(), 'test')

    def test_path(self):
        self.create_file('test.txt', 'test')
        self.assertEqual(self.storage.path('test.txt'),
                         os.path.join(settings.MEDIA_ROOT, 'test.txt'))

    def test_save(self):
        filename = self.storage.save('test.txt', ContentFile('test'))
        self.assertEqual(filename, 'test.txt')
        self.assertEqual(self.get_file('test.txt'), 'test')

    def test_save_existing(self):
        self.storage.save('test.txt', ContentFile('test'))
        filename = self.storage.save('test.txt', ContentFile('test2'))
        # a new file is generated
        self.assertEqual(filename, 'test_1.txt')
        self.assertEqual(self.get_file('test_1.txt'), 'test2')

    def test_save_readonly(self):
        self.http_server.readonly = True
        self.assertRaises(urllib2.HTTPError, self.storage.save, 'test.txt', ContentFile('test'))
        self.assertIn("Failed to create", self.get_log())

    def test_save_dilettante(self):
        self.http_server.override_code = 202
        self.assertRaises(UnexpectedStatusCode, self.storage.save, 'test.txt', ContentFile('test'))
        self.assertIn("Failed to create", self.get_log())

    def test_size(self):
        self.create_file('test.txt', 'test')
        self.assertEqual(self.storage.size('test.txt'), 4)

    def test_url(self):
        self.create_file('test.txt', 'test')
        self.assertEqual(self.storage.url('test.txt'),
                'http://media.example.com/test.txt')


class StorageTestCaseVariantsMixin(object):

    # Adapt tests of methods that behave differently in DistributedStorage
    # and HybridStorage. Disable tests that are non deterministic with
    # DistributedStorage and an inconsistent state between the servers.

    def test_accessed_time(self):
        self.assertRaises(NotImplementedError, self.storage.accessed_time, 'test.txt')

    test_accessed_time_non_existing = test_accessed_time

    def test_open_broken(self):
        if len(self.storage.hosts) > 1:
            return
        self.http_server.override_code = 500
        self.assertRaises(urllib2.HTTPError, self.storage.open, 'test.txt')
        self.assertIn("Failed to download", self.get_log())

    def test_open_dilettante(self):
        if len(self.storage.hosts) > 1:
            return
        self.http_server.override_code = 202
        self.assertRaises(UnexpectedStatusCode, self.storage.open, 'test.txt')
        self.assertIn("Failed to download", self.get_log())

    def test_created_time(self):
        self.assertRaises(NotImplementedError, self.storage.created_time, 'test.txt')

    test_created_time_non_existing = test_created_time

    def test_exists_broken(self):
        if len(self.storage.hosts) > 1:
            return
        self.http_server.override_code = 500
        self.assertRaises(urllib2.HTTPError, self.storage.exists, 'test.txt')
        self.assertIn("Failed to check", self.get_log())

    def test_exists_dilettante(self):
        if len(self.storage.hosts) > 1:
            return
        self.http_server.override_code = 202
        self.assertRaises(UnexpectedStatusCode, self.storage.exists, 'test.txt')
        self.assertIn("Failed to check", self.get_log())

    def test_listdir(self):
        self.assertRaises(NotImplementedError, self.storage.listdir, 'test')

    test_listdir_non_existing = test_listdir

    def test_modified_time(self):
        self.assertRaises(NotImplementedError, self.storage.modified_time, 'test.txt')

    test_modified_time_non_existing = test_modified_time

    def test_path(self):
        self.assertRaises(NotImplementedError, self.storage.path, 'test.txt')

    # This blows up in get_available_name with a different log message,
    # so we duplicate the test here.
    def test_save_dilettante(self):
        self.http_server.override_code = 202
        self.assertRaises(UnexpectedStatusCode, self.storage.save, 'test.txt', ContentFile('test'))
        self.assertIn("Failed to check", self.get_log())

    def test_size_broken(self):
        if len(self.storage.hosts) > 1:
            return
        self.http_server.override_code = 500
        self.create_file('test.txt', 'test')
        self.assertRaises(urllib2.HTTPError, self.storage.size, 'test.txt')
        self.assertIn("Failed to get the size", self.get_log())

    def test_size_dilettante(self):
        if len(self.storage.hosts) > 1:
            return
        self.http_server.override_code = 202
        self.create_file('test.txt', 'test')
        self.assertRaises(UnexpectedStatusCode, self.storage.size, 'test.txt')
        self.assertIn("Failed to get the size", self.get_log())


class CoverageTestCaseMixin(object):

    # This test case exercises some code paths that are not stressed by the
    # main tests because they handle unexpected situations.

    def test_invalid_base_url(self):
        self.assertRaises(ValueError, self.storage_class,
                base_url='http://example.com/?a_query_does_not_make_sense')
        self.assertRaises(ValueError, self.storage_class,
                base_url='http://example.com/#a_fragment_does_not_make_sense')

    def test_open_only_for_read(self):
        self.create_file('test.txt', 'test')
        self.storage._open('test.txt', 'rb').close()
        self.assertRaises(IOError, self.storage._open, 'test.txt', 'wb')


class CoverageTestCaseVariantsMixin(object):

    def test_fatal_exceptions_disabled(self):
        DistributedStorage.fatal_exceptions = False
        try:
            DistributedStorage()
            self.assertIn("You have been warned.", self.get_log())
        finally:
            DistributedStorage.fatal_exceptions = True

    def test_save_over_existing_file(self):
        self.storage._save('test.txt', ContentFile('test'))
        self.assertEqual(self.get_file('test.txt'), 'test')
        # Hijack the check for an existing file. This is not sufficient with
        # FileSystemStorage, and as a consquence with HybridStorage too,
        # so the test only applies to DistributedStorage.
        self.storage.get_available_name = lambda name: name
        self.storage._save('test.txt', ContentFile('test2'))
        self.assertEqual(self.get_file('test.txt'), 'test2')
        self.assertIn("PUT on existing file", self.get_log())


class UseDistributedStorageMixin(object):

    storage_class = DistributedStorage
    use_fs = False


class UseHybridStorageMixin(object):

    storage_class = HybridStorage
    use_fs = True


class DistributedStorageTestCase(
        StorageTestCaseVariantsMixin, StorageTestCaseMixin,
        StorageUtilitiesMixin,
        UseDistributedStorageMixin, unittest.TestCase):

    pass


class HybridStorageTestCase(
        StorageTestCaseMixin,
        StorageUtilitiesMixin,
        UseHybridStorageMixin, unittest.TestCase):

    pass


class DistributedStorageWithTwoServersTestCase(
        StorageTestCaseVariantsMixin, StorageTestCaseMixin,
        StorageUtilitiesWithTwoServersMixin,
        UseDistributedStorageMixin, unittest.TestCase):

    pass


class HybridStorageWithTwoServersTestCase(
        StorageTestCaseMixin,
        StorageUtilitiesWithTwoServersMixin,
        UseHybridStorageMixin, unittest.TestCase):

    pass


class DistributedStorageCoverageTestCase(
        CoverageTestCaseVariantsMixin, CoverageTestCaseMixin,
        StorageUtilitiesMixin,
        UseDistributedStorageMixin, unittest.TestCase):

    pass


class HybridStorageCoverageTestCase(
        CoverageTestCaseMixin,
        StorageUtilitiesMixin,
        UseHybridStorageMixin, unittest.TestCase):

    pass
