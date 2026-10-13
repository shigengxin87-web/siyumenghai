import os
os.environ.setdefault('DTK_API_KEY','unit-test-internal-key')
import unittest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient
import engine

class Contract(unittest.TestCase):
 def setUp(self): self.c=TestClient(engine.app);self.headers={'Authorization':'Bearer '+engine.secret};engine.cache.clear()
 def test_auth_required(self): self.assertEqual(self.c.post('/api/v1/parse',json={'url':'https://www.douyin.com/video/7694206162778017058'}).status_code,401)
 def test_no_false_success(self):
  with patch.object(engine,'fetch_data',new=AsyncMock(return_value={'status_code':0})):
   r=self.c.post('/api/v1/parse',headers=self.headers,json={'url':'https://www.douyin.com/video/7694206162778017058'})
   self.assertEqual(r.status_code,502);self.assertFalse(r.json()['success'])
 def test_host_boundary(self):
  for url in ['http://www.douyin.com/video/1234567890123456','https://douyin.com.evil.test/video/1234567890123456','https://user:secret@www.douyin.com/video/1234567890123456','https://www.douyin.com:444/video/1234567890123456']:
   with self.assertRaises(ValueError):engine.valid_url(url)
 def test_album_preserves_images(self):
  d=engine.shape({'aweme_id':'7694206162778017058','images':[{'url_list':['https://p3.douyinpic.com/test.jpg']}],'video':{'play_addr':{'url_list':['https://v.douyinvod.com/test.mp4']}}})
  self.assertIsNone(d['media']['video']);self.assertEqual(len(d['media']['images']),1)
 def test_limit_translates_without_secrets(self):
  with patch.object(engine,'fetch_data',new=AsyncMock(side_effect=engine.UpstreamError(429))):
   r=self.c.post('/api/v1/parse',headers=self.headers,json={'url':'https://www.douyin.com/video/7694206162778017058'})
   self.assertEqual(r.status_code,429);self.assertNotIn(engine.secret,r.text)
 def test_wrong_id_rejected(self):
  with patch.object(engine,'fetch_data',new=AsyncMock(return_value={'aweme_detail':{'aweme_id':'7685216705279513690'}})):
   r=self.c.post('/api/v1/parse',headers=self.headers,json={'url':'https://www.douyin.com/video/7694206162778017058'})
   self.assertEqual(r.status_code,502)
if __name__=='__main__':unittest.main()
