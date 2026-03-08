import time
import unittest
from unittest.mock import patch
from core.cache import SmartCache

class TestSmartCacheCleanup(unittest.TestCase):
    def setUp(self):
        self.cache = SmartCache(default_ttl=100)

    def test_cleanup_empty(self):
        """Test cleanup on an empty cache."""
        removed = self.cache.cleanup()
        self.assertEqual(removed, 0)
        self.assertEqual(len(self.cache._cache), 0)
        self.assertEqual(self.cache.evictions, 0)

    def test_cleanup_no_expired(self):
        """Test cleanup when no entries are expired."""
        with patch('time.time', return_value=1000.0):
            self.cache.set("value1", "key1", ttl=100)
            self.cache.set("value2", "key2", ttl=200)

        with patch('time.time', return_value=1050.0):
            removed = self.cache.cleanup()
            self.assertEqual(removed, 0)
            self.assertEqual(len(self.cache._cache), 2)
            self.assertEqual(self.cache.evictions, 0)

    def test_cleanup_all_expired(self):
        """Test cleanup when all entries are expired."""
        with patch('time.time', return_value=1000.0):
            self.cache.set("value1", "key1", ttl=10)
            self.cache.set("value2", "key2", ttl=20)

        with patch('time.time', return_value=1100.0):
            removed = self.cache.cleanup()
            self.assertEqual(removed, 2)
            self.assertEqual(len(self.cache._cache), 0)
            self.assertEqual(self.cache.evictions, 2)

    def test_cleanup_mixed(self):
        """Test cleanup with mixed expired and active entries."""
        with patch('time.time', return_value=1000.0):
            # Expires at 1010
            self.cache.set("expired1", "key1", ttl=10)
            # Expires at 1200
            self.cache.set("active1", "key2", ttl=200)
            # Expires at 1005
            self.cache.set("expired2", "key3", ttl=5)

        with patch('time.time', return_value=1050.0):
            removed = self.cache.cleanup()
            self.assertEqual(removed, 2)
            self.assertEqual(len(self.cache._cache), 1)
            # Verify that the active entry is still there
            active_key = self.cache._generate_key("key2")
            self.assertIn(active_key, self.cache._cache)
            self.assertEqual(self.cache.evictions, 2)

    def test_cleanup_stats_consistency(self):
        """Test that cleanup correctly updates the evictions stat."""
        with patch('time.time', return_value=1000.0):
            self.cache.set("v1", "k1", ttl=10)

        with patch('time.time', return_value=1100.0):
            self.cache.cleanup()
            stats = self.cache.get_stats()
            self.assertEqual(stats['evictions'], 1)
            self.assertEqual(stats['size'], 0)

if __name__ == '__main__':
    unittest.main()
