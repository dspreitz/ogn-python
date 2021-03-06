import unittest
import unittest.mock as mock

from ogn.utils import get_ddb, get_trackable, get_country_code
from ogn.model import AircraftType


class TestStringMethods(unittest.TestCase):
    def test_get_devices(self):
        devices = get_ddb()
        self.assertGreater(len(devices), 1000)

    def test_get_ddb_from_file(self):
        devices = get_ddb('tests/custom_ddb.txt')
        self.assertEqual(len(devices), 6)
        device = devices[0]

        self.assertEqual(device.address, 'DD4711')
        self.assertEqual(device.aircraft, 'HK36 TTC')
        self.assertEqual(device.registration, 'D-EULE')
        self.assertEqual(device.competition, 'CU')
        self.assertTrue(device.tracked)
        self.assertTrue(device.identified)
        self.assertEqual(device.aircraft_type, AircraftType.glider_or_motor_glider)

    def test_get_trackable(self):
        devices = get_ddb('tests/custom_ddb.txt')
        trackable = get_trackable(devices)
        self.assertEqual(len(trackable), 4)
        self.assertIn('FLRDD4711', trackable)
        self.assertIn('FLRDD0815', trackable)
        self.assertIn('OGNDEADBE', trackable)
        self.assertIn('ICA999999', trackable)

    def test_get_country_code(self):
        latitude = 48.0
        longitude = 11.0
        country_code = get_country_code(latitude, longitude)
        self.assertEquals(country_code, 'de')

    def test_get_country_code_bad(self):
        latitude = 0.0002274
        longitude = -0.0009119
        country_code = get_country_code(latitude, longitude)
        self.assertEqual(country_code, None)

    @mock.patch('ogn.utils.Nominatim')
    def test_gec_country_code_exception(self, nominatim_mock):
        from geopy.exc import GeocoderTimedOut
        instance = nominatim_mock.return_value

        instance.reverse.side_effect = GeocoderTimedOut('Too busy')
        country_code = get_country_code(0, 0)
        self.assertIsNone(country_code)
