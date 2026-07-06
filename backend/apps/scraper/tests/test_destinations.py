"""
Destination secret masking: API responses must never contain decrypted secrets,
and PATCHing back a masked value must keep the stored secret intact.
"""
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from apps.scraper.models import ScrapeJob, DataDestination

MASK = '********'


class DestinationSecretMaskingTests(APITestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username='owner', email='owner@example.com', password='pass12345'
        )
        self.client.force_authenticate(self.user)
        self.job = ScrapeJob.objects.create(
            user=self.user,
            name='Test job',
            mode=ScrapeJob.Mode.PROMPT,
            configuration={'urls': ['https://example.com'], 'prompt': 'titles'},
        )

    def _create(self, dest_type, config, name='dest'):
        resp = self.client.post('/api/scraper/destinations/', {
            'job': self.job.id, 'name': name,
            'dest_type': dest_type, 'config': config,
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.content)
        return resp.json()

    def test_postgres_dsn_masked_in_responses(self):
        dsn = 'postgresql://user:dbpass@dbhost:5432/mydb'
        data = self._create('postgres', {'dsn': dsn, 'table': 'rows'})
        self.assertEqual(data['config']['dsn'], MASK)
        self.assertEqual(data['config']['table'], 'rows')
        self.assertNotIn(dsn, str(data))

        # detail + list views mask too
        detail = self.client.get(f"/api/scraper/destinations/{data['id']}/").json()
        self.assertEqual(detail['config']['dsn'], MASK)
        listed = self.client.get('/api/scraper/destinations/').json()
        rows = listed['results'] if isinstance(listed, dict) and 'results' in listed else listed
        self.assertTrue(all(d['config'].get('dsn') == MASK for d in rows))

    def test_webhook_url_and_secret_masked(self):
        data = self._create('webhook', {
            'url': 'https://hooks.example.com/x?token=abc',
            'secret': 'hmac-key',
        })
        self.assertEqual(data['config']['url'], MASK)
        self.assertEqual(data['config']['secret'], MASK)

    def test_patch_with_masked_values_preserves_secrets(self):
        dsn = 'postgresql://user:dbpass@dbhost:5432/mydb'
        data = self._create('postgres', {'dsn': dsn, 'table': 'rows'})

        # Simulate the edit UI sending back the masked config with a rename
        resp = self.client.patch(
            f"/api/scraper/destinations/{data['id']}/",
            {'name': 'renamed', 'config': {'dsn': MASK, 'table': 'rows2'}},
            format='json',
        )
        self.assertEqual(resp.status_code, 200, resp.content)

        dest = DataDestination.objects.get(id=data['id'])
        self.assertEqual(dest.decrypted_config['dsn'], dsn)
        self.assertEqual(dest.decrypted_config['table'], 'rows2')
        # still encrypted at rest
        self.assertTrue(str(dest.config['dsn']).startswith('enc:'))

    def test_patch_with_new_secret_overwrites(self):
        data = self._create('webhook', {'url': 'https://hooks.example.com/a'})
        resp = self.client.patch(
            f"/api/scraper/destinations/{data['id']}/",
            {'config': {'url': 'https://hooks.example.com/b'}},
            format='json',
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        dest = DataDestination.objects.get(id=data['id'])
        self.assertEqual(dest.decrypted_config['url'], 'https://hooks.example.com/b')
