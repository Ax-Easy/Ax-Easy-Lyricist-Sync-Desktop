"""Whisper size by hardware (mocked VRAM), the one-model setup plan, picking/deleting sizes and the
on-demand model download (resumable, SHA256-checked) from a local server. No network needed."""
import hashlib, json, os, sys, tempfile, threading, unittest
from unittest import mock
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'app'))
sys.path.insert(0, os.path.join(HERE, '..', 'tools'))
os.environ['LYRICIST_SYNC_HOME'] = tempfile.mkdtemp()
from lyricist_sync import bootstrap  # noqa: E402


class TestTier(unittest.TestCase):
    def test_vram_tiers(self):
        cases = [(None, 'small'), (0, 'small'), (2.0, 'small'), (4.0, 'small'), (5.4, 'small'),
                 (5.8, 'medium'), (6.0, 'medium'), (8.0, 'medium'), (10.0, 'medium'), (11.0, 'medium'),
                 (11.7, 'large-v3-turbo'), (12.0, 'large-v3-turbo'), (16.0, 'large-v3-turbo'), (20.0, 'large-v3-turbo'),
                 (23.0, 'large-v3-turbo'), (23.7, 'large-v3'), (24.0, 'large-v3'), (48.0, 'large-v3'), (80.0, 'large-v3')]
        for vram, want in cases:
            self.assertEqual(bootstrap.whisper_tier(vram, 'cuda'), want, vram)
        for vram in (None, 8.0, 24.0):   # CPU build: always small
            self.assertEqual(bootstrap.whisper_tier(vram, 'cpu'), 'small')

    def test_detect_gpu_vram(self):
        """nvidia-smi output of an RTX 3090 (24576 MiB) -> 24 GB -> large-v3."""
        out = mock.Mock(stdout='NVIDIA GeForce RTX 3090, 591.44, 24576\n')
        with mock.patch.object(bootstrap, 'run', return_value=out), \
                mock.patch.object(bootstrap.shutil, 'which', return_value=__file__):
            g = bootstrap.detect_gpu()
        self.assertEqual(g['name'], 'NVIDIA GeForce RTX 3090')
        self.assertEqual(g['vram_gb'], 24.0)
        self.assertTrue(g['nvidia'])
        self.assertEqual(bootstrap.whisper_tier(g['vram_gb'], bootstrap.recommended_variant(dict(g, cuda_driver=13000))), 'large-v3')
        for line, gb, tier in (('NVIDIA GeForce RTX 3060, 560.1, 12288', 12.0, 'large-v3-turbo'),
                               ('NVIDIA GeForce RTX 3070, 560.1, 8192', 8.0, 'medium'),
                               ('NVIDIA GeForce GTX 1650, 560.1, 4096', 4.0, 'small'),
                               ('NVIDIA RTX A6000, 560.1, 49140', 48.0, 'large-v3'),
                               ('Some GPU, 1.0, [N/A]', None, 'small')):
            d = bootstrap.parse_smi(line)
            self.assertEqual(d.get('vram_gb'), gb, line)
            self.assertEqual(bootstrap.whisper_tier(d.get('vram_gb'), 'cuda'), tier, line)

    def test_plan_has_one_whisper(self):
        m = bootstrap.manifest()
        names = [w['name'] for w in m['whisper_models']]
        self.assertEqual(names, ['small', 'medium', 'large-v3-turbo', 'large-v3'])
        for w in m['whisper_models']:
            self.assertIn(w['sha256'], w['url'])          # openai's URLs carry the SHA256
            self.assertTrue(w['dest'].startswith('models/whisper/'))
        for tier in names + [None]:
            items = [i for i in bootstrap.plan('cuda', whisper=tier) if i['kind'] == 'model']
            wh = [i for i in items if bootstrap.model_group(i) == 'whisper']
            self.assertEqual(len(wh), 1, tier)
            self.assertTrue(wh[0]['dest'].replace('\\', '/').endswith('/%s.pt' % (tier or 'small')))
            self.assertEqual(sorted(bootstrap.model_group(i) for i in items), ['demucs', 'mms', 'whisper'])
        # the plan without a tier is exactly what 1.2.0 installed (torch, wheels, models unchanged)
        self.assertEqual(m['version'], 1)
        big = bootstrap.total_size('cuda', whisper='large-v3') - bootstrap.total_size('cuda')
        self.assertEqual(big, m['whisper_models'][3]['size'] - m['whisper_models'][0]['size'])

    def test_effective_and_delete(self):
        home = tempfile.mkdtemp()
        models = bootstrap.whisper_models()

        def fake(name):
            p = bootstrap.whisper_path(name, home)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, 'wb') as f:
                f.truncate(models[name]['size'])     # sparse file of the right size
            open(p + '.ok', 'w').close()

        fake('small')
        inst = bootstrap.whisper_installed(home)
        self.assertEqual(inst, ['small'])
        # 1.2.0 upgrade on a 24 GB GPU: tier large-v3 not there yet -> keeps using small
        self.assertEqual(bootstrap.effective_whisper('auto', 'large-v3', inst), 'small')
        fake('large-v3-turbo')
        inst = bootstrap.whisper_installed(home)
        self.assertEqual(bootstrap.effective_whisper('auto', 'large-v3', inst), 'large-v3-turbo')
        self.assertEqual(bootstrap.effective_whisper('auto', 'medium', inst), 'small')   # never bigger than the tier
        self.assertEqual(bootstrap.effective_whisper('small', 'large-v3', inst), 'small')
        self.assertEqual(bootstrap.effective_whisper('large-v3-turbo', 'small', inst), 'large-v3-turbo')
        with self.assertRaises(RuntimeError):
            bootstrap.delete_whisper('large-v3-turbo', 'large-v3-turbo', home)   # in use
        freed = bootstrap.delete_whisper('small', 'large-v3-turbo', home)
        self.assertEqual(freed, models['small']['size'])
        self.assertEqual(bootstrap.whisper_installed(home), ['large-v3-turbo'])
        with self.assertRaises(RuntimeError):
            bootstrap.delete_whisper('large-v3-turbo', 'small', home)            # the last one


class TestModelDownload(unittest.TestCase):
    """Switching to another size downloads only that file, resumes a .part and checks SHA256."""

    def setUp(self):
        import http.server
        import serve_throttled
        self.root = tempfile.mkdtemp()
        self.payload = os.urandom(3 * 1024 * 1024 + 123)
        with open(os.path.join(self.root, 'medium.pt'), 'wb') as f:
            f.write(self.payload)
        self.srv = http.server.ThreadingHTTPServer(('127.0.0.1', 0), serve_throttled.make_handler(self.root, 0, {}))
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        os.environ['LYRICIST_SYNC_MIRROR'] = 'http://127.0.0.1:%d/' % self.srv.server_address[1]
        real = bootstrap.manifest()
        man = json.loads(json.dumps(real))
        for w in man['whisper_models']:
            if w['name'] == 'medium':
                w.update(size=len(self.payload), sha256=hashlib.sha256(self.payload).hexdigest())
        self.patch = mock.patch.object(bootstrap, 'manifest', return_value=man)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.srv.shutdown()
        os.environ.pop('LYRICIST_SYNC_MIRROR', None)

    def test_switch_download_resume(self):
        dest = bootstrap.whisper_path('medium')
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest + '.part', 'wb') as f:
            f.write(self.payload[:1000000])      # an interrupted earlier download
        dl = bootstrap.ModelDownload('medium')
        self.assertEqual([i['dest'] for i in dl.setup.items], [dest])   # only this one file
        self.assertEqual(dl.run(), 'medium')
        with open(dest, 'rb') as f:
            self.assertEqual(f.read(), self.payload)
        self.assertTrue(os.path.exists(dest + '.ok'))
        steps = dl.state.snapshot()[0]
        self.assertEqual(steps['dl_whisper']['status'], 'done')
        self.assertEqual(steps['verify']['status'], 'done')
        logs = '\n'.join(dl.state.logs)
        self.assertIn('Resuming', logs)
        self.assertIn('medium', bootstrap.whisper_installed())
        # already there: nothing downloaded again
        dl2 = bootstrap.ModelDownload('medium')
        self.assertEqual(dl2.run(), 'medium')
        self.assertNotIn('Downloaded', '\n'.join(dl2.state.logs))

    def test_bad_checksum(self):
        with open(os.path.join(self.root, 'medium.pt'), 'wb') as f:
            f.write(b'x' * len(self.payload))
        dl = bootstrap.ModelDownload('medium')
        with mock.patch.object(bootstrap.time, 'sleep'):
            with self.assertRaises(RuntimeError):
                dl.run()
        self.assertNotIn('medium', bootstrap.whisper_installed())
        self.assertEqual(dl.state.snapshot()[0]['dl_whisper']['status'], 'failed')


if __name__ == '__main__':
    unittest.main()
