import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from drivebrief_api.app import create_app
from drivebrief_api.planning import plan
from drivebrief_api.pipeline_settings import load_config
from drivebrief_api.timing_calibration import profile,validate,calibrated_config
from test_quality import observation


class TimingCalibrationTests(unittest.TestCase):
    def records(self,prefix):
        return [observation(prefix+str(i//4),i,20+i*7) for i in range(12)]
    def model(self):
        baseline=load_config()
        model=profile(self.records('train-'))
        testing=self.records('validation-')[:6]
        for i,row in enumerate(testing):row['article_id']='validation-'+str(i//3)
        return validate(model,testing,baseline)
    def test_training_freezes_coefficients_before_disjoint_validation(self):
        raw=profile(self.records('train-'))
        self.assertIsNone(raw['independent_validation'])
        model=self.model()
        self.assertTrue(model['independent_validation']['accepted'])
        self.assertFalse(model['independent_validation']['fit_on_validation'])
        self.assertLess(model['independent_validation']['candidate']['mae_seconds'],1e-8)
        self.assertEqual(raw['coefficients'],model['coefficients'])
    def test_training_leakage_and_environment_changes_rejected(self):
        rows=self.records('train-');model=profile(rows)
        with self.assertRaises(ValueError):validate(model,rows,load_config())
        rows=self.records('test-')[:6]
        for i,row in enumerate(rows):row['article_id']='test-'+str(i//3);row['sdk_version']='other-sdk'
        with self.assertRaises(ValueError):validate(model,rows,load_config())
    def test_model_only_changes_timing_for_matching_sdk_and_locale(self):
        model=self.model();config=load_config();before=copy.deepcopy(config)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'profile.json';path.write_text(json.dumps(model))
            self.assertIs(config,calibrated_config(config,path,'wrong-sdk','ko-KR'))
            self.assertIs(config,calibrated_config(config,path,None,None))
            candidate=calibrated_config(config,path,model['sdk_version'],'ko-KR')
            self.assertEqual(candidate['weights'],before['weights'])
            self.assertEqual(candidate['event'],before['event'])
            self.assertEqual(candidate['length_seconds'],before['length_seconds'])
            self.assertEqual(config,before)
            self.assertEqual(candidate['_timing_profile'],'calibrated')
    def test_unvalidated_or_nonfinite_model_is_not_used(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'model.json';model=profile(self.records('train-'));path.write_text(json.dumps(model))
            with self.assertRaises(ValueError):calibrated_config(load_config(),path,'test-fixture','ko-KR')
            model['coefficients']['characters_per_second']=float('nan');path.write_text(json.dumps(model))
            with self.assertRaises(ValueError):calibrated_config(load_config(),path,'test-fixture','ko-KR')


def document():
    return dict(schema_version='approved-briefing-v1',fictional_only=True,playback_requires_user_action=True,articles=[
        dict(article_id='article-'+str(i),title=title,source='자체 가상자료',source_url='https://example.com/'+str(i),
             published_at='2026-11-13T0'+str(9-i)+':00:00+09:00',tts_sentences=[text],one_line=title,detail=title,
             categories=['경제'],mock=True,validation=dict(status='approved',approved=True,review_required=False))
        for i,(title,text) in enumerate([('독립 정원 소식','가'*6),('가상 연구소 소개','나'*5),('별도 체육관 안내','다'*5)])])


class BudgetPackingTests(unittest.TestCase):
    def config(self,seconds=10):
        config=load_config();config['characters_per_second']=1;config['sentence_pause_seconds']=0
        config['length_seconds']={k:seconds for k in config['length_seconds']}
        return config
    def test_time_objective_improves_budget_fill_without_changing_scores(self):
        doc=document();config=self.config()
        before=plan(doc,'중간',[],config)
        after=plan(doc,'중간',[],config,budget_packing=True)
        self.assertEqual(before['estimated_seconds'],6)
        self.assertEqual(after['estimated_seconds'],10)
        self.assertEqual(after['planning_method'],'budget_prefix')
        full=plan(doc,'중간',[],self.config(3600))
        scores={a['article_id']:a['importance_score'] for a in full['articles']}
        for article in after['articles']:self.assertEqual(article['importance_score'],scores[article['article_id']])
    def test_empty_news_oversize_sentences_and_long_budgets_do_not_pad(self):
        self.assertEqual(plan(dict(document(),articles=[]),'중간',[],self.config(),budget_packing=True)['articles'],[])
        self.assertEqual(plan(document(),'중간',[],self.config(1),budget_packing=True)['articles'],[])
        for seconds in [30,60,120,600,1200,1800]:
            result=plan(document(),'중간',[],self.config(seconds),budget_packing=True)
            self.assertLessEqual(result['estimated_seconds'],seconds)
            self.assertTrue(result['shortage'])
            sentences=[s for a in result['articles'] for s in a['tts_sentences']]
            self.assertEqual(len(sentences),len(set(sentences)))
    def test_prefixes_and_approval_boundary_are_preserved(self):
        doc=document();doc['articles'][1]['tts_sentences']=['나'*5,'라'*5]
        result=plan(doc,'중간',[],self.config(),budget_packing=True)
        original={a['article_id']:a for a in doc['articles']}
        for article in result['articles']:
            self.assertEqual(article['tts_sentences'],original[article['article_id']]['tts_sentences'][:len(article['tts_sentences'])])
            self.assertEqual(article['detail'],original[article['article_id']]['detail'])
        doc['articles'][0]['validation']['approved']=False
        with self.assertRaises(ValueError):plan(doc,'중간',[],self.config(),budget_packing=True)
    def test_api_profile_is_explicit_and_does_not_change_length_selection(self):
        class Store:
            def briefing(self,limit=None):return document()
        with tempfile.TemporaryDirectory() as directory:
            model=TimingCalibrationTests().model();path=Path(directory)/'model.json';path.write_text(json.dumps(model))
            with patch.dict(os.environ,{'DRIVEBRIEF_TIMING_MODEL':str(path),'DRIVEBRIEF_BUDGET_PACKING':'1'}):
                client=TestClient(create_app(review_store=Store()))
                response=client.get('/v1/briefings/plan?length=중간',headers={'X-DriveBrief-TTS-SDK':'test-fixture','X-DriveBrief-TTS-Locale':'ko-KR'})
                self.assertEqual(response.status_code,200)
                self.assertEqual(response.json()['timing_profile'],'calibrated')
                self.assertEqual(response.json()['target_seconds'],60)
                self.assertEqual(client.get('/v1/briefings/plan?length=중간').json()['timing_profile'],'baseline')

    def test_state_limit_falls_back_to_existing_planner(self):
        config=self.config();doc=document()
        with patch('drivebrief_api.algorithm_v2.budget_candidate',side_effect=ValueError('offline_state_limit_exceeded')):
            result=plan(doc,'중간',[],config,budget_packing=True)
        original=plan(doc,'중간',[],config)
        self.assertEqual(result['articles'],original['articles'])
        self.assertEqual(result['planning_method'],'legacy_fallback')

    def test_shared_sentence_is_not_repeated_across_articles(self):
        doc=document();doc['articles'][1]['tts_sentences']=['가'*6,'나'*5]
        result=plan(doc,'중간',[],self.config(30),budget_packing=True)
        sentences=[s for a in result['articles'] for s in a['tts_sentences']]
        self.assertEqual(len(sentences),len(set(sentences)))
