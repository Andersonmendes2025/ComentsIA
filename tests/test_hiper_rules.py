"""Isolated regression checks; no credentials, database or network required."""
import ast
import logging
from pathlib import Path
import sys
from types import SimpleNamespace, ModuleType
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]

def function(path, name, namespace=None):
    tree = ast.parse((ROOT / path).read_text(encoding='utf-8'))
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    node.decorator_list = []
    ns = {} if namespace is None else namespace
    exec(compile(ast.Module(body=[node], type_ignores=[]), path, 'exec'), ns)
    return ns[name]

class HiperRulesTests(unittest.TestCase):
    def test_length_rules_are_exclusive(self):
        rule = function('services/ai_service.py', 'get_reply_length_instructions')
        self.assertIn('8 a 15', rule(True))
        self.assertNotIn('3 a 5 frases', rule(True))
        self.assertIn('3 a 5 frases', rule(False))
        self.assertIn('não invente', rule(True))

    def test_plan_limits_including_first_free_use(self):
        for plan, used, expected in [('free',None,False),('unknown',None,False),('pro',None,True),('pro',1,True),('pro',2,False),('business',100,True)]:
            query = SimpleNamespace(filter_by=lambda **kw: SimpleNamespace(first=lambda: None if used is None else SimpleNamespace(quantidade_usos=used)))
            fn = function('main.py','usuario_pode_usar_resposta_especial',{'get_data_hoje_brt':lambda:None,'get_user_plan':lambda _:plan,'PLANOS':{'free':{'hiper_dia':0},'pro':{'hiper_dia':2},'business':{'hiper_dia':None}},'RespostaEspecialUso':SimpleNamespace(query=query)})
            self.assertEqual(fn('test'), expected, (plan,used))

    def test_automatic_prompt_and_failure(self):
        captured=[]
        def create(**kw):
            captured.append(kw)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='Resposta da IA'))])
        client=SimpleNamespace(with_options=lambda **kw: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
        main=ModuleType('main'); main.client=client
        main.get_user_settings=lambda _: {'business_name':'Global','gbp_tone':'profissional','idioma_resposta':'Português','contexto_personalizado':'Contexto global'}
        ai=ModuleType('services.ai_service')
        ai.limpar_texto_review=lambda x:x
        ai.limpar_resposta_ia=lambda x:x
        ai.get_tone_instructions=lambda x:'TOM:'+x
        ai.get_language_instructions=lambda x:('SISTEMA:'+x,'IDIOMA:'+x)
        ai.get_reply_length_instructions=function('services/ai_service.py','get_reply_length_instructions')
        fn=function('google_auto.py','_generate_reply_for',{'Optional':__import__('typing').Optional,'GoogleLocation':object,'logging':logging})
        with patch.dict(sys.modules,{'main':main,'services.ai_service':ai}):
            loc=SimpleNamespace(business_name='Ficha local',tone='empatico',idioma_resposta='Inglês',contexto_personalizado='Contexto local')
            self.assertEqual(fn('test',1,'Barulho','Cliente',True,loc),'Resposta da IA')
            prompt=captured[-1]['messages'][1]['content']
            for text in ['8 a 15','Ficha local','TOM:empatico','IDIOMA:Inglês','Contexto local','somente informações pertinentes']:
                self.assertIn(text,prompt)
            self.assertNotIn('3 a 5 frases',prompt)
            self.assertNotIn('Contexto global',prompt)
            main.client=SimpleNamespace(with_options=lambda **kw: (_ for _ in ()).throw(RuntimeError('API unavailable')))
            with self.assertLogs(level='ERROR'):
                self.assertEqual(fn('test',1,'Barulho','Cliente',True,loc),'')

if __name__ == '__main__':
    unittest.main()

