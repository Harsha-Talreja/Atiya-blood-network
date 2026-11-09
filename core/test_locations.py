from django.test import TestCase

from core.locations import city_names, grouped_locations


class GroupedLocationTests(TestCase):
    def test_cities_are_alphabetical(self):
        self.assertEqual(city_names(), sorted(city_names()))
        self.assertEqual(len(city_names()), 6)

    def test_other_is_always_last_inside_each_city(self):
        for city, areas in grouped_locations():
            with self.subTest(city=city):
                self.assertEqual(areas[-1].area, "Other")
                rest = [a.area for a in areas[:-1]]
                self.assertEqual(rest, sorted(rest))

    def test_every_area_appears_once(self):
        total = sum(len(areas) for _, areas in grouped_locations())
        self.assertEqual(total, 40)
