"""Resumable, SHA256-verified downloads (needs network)."""
import hashlib, os, sys, tempfile, unittest, urllib.request
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'app'))


class TestDownload(unittest.TestCase):
    def test_resume(self):
        os.environ['LYRICIST_SYNC_HOME'] = tempfile.mkdtemp()
        from lyricist_sync import bootstrap
        m = bootstrap.manifest()
        it = dict(next(w for w in m['wheels'] if w['name'].startswith('colorama')))
        try:
            data = urllib.request.urlopen(it['url'], timeout=30).read()
        except Exception as e:
            self.skipTest('offline: %s' % e)
        self.assertEqual(hashlib.sha256(data).hexdigest(), it['sha256'])
        it['dest'] = os.path.join(os.environ['LYRICIST_SYNC_HOME'], 'downloads', it['name'])
        it['label'] = 'colorama'
        os.makedirs(os.path.dirname(it['dest']), exist_ok=True)
        with open(it['dest'] + '.part', 'wb') as f:
            f.write(data[:len(data) // 2])  # simulate an interrupted download
        logs = []
        s = bootstrap.Setup('cpu', on_log=logs.append)
        s._download(it, 0)
        self.assertTrue(os.path.exists(it['dest'] + '.ok'))
        with open(it['dest'], 'rb') as f:
            self.assertEqual(f.read(), data)
        self.assertTrue(any('Resuming' in l for l in logs), logs)
        self.assertTrue(s._verified(it))

    def test_plan_sizes(self):
        from lyricist_sync import bootstrap
        self.assertGreater(bootstrap.total_size('cuda'), 4.4e9)
        self.assertLess(bootstrap.total_size('cpu'), 2.3e9)

    def test_model_steps(self):
        """Each model download step gets exactly its own model, also with Windows paths."""
        from lyricist_sync import bootstrap
        for sep in ('/', '\\'):
            items = [dict(m, dest='C:' + sep + sep.join(['home'] + m['dest'].split('/'))) for m in bootstrap.manifest()['models']]
            groups = sorted(bootstrap.model_group(m) for m in items)
            self.assertEqual(groups, ['demucs', 'mms', 'whisper'], sep)


if __name__ == '__main__':
    unittest.main()
