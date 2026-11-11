from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import email_alertas as mail
import juridico
import mandados

NUMBER = '5004310-40.2026.8.21.0018'


class MandateEmails(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.store = juridico.Store(Path(temporary.name) / 'db.sqlite')
        self.actor = self.store.create_user({'nome': 'Admin', 'login': 'admin', 'senha': 'senha-forte-123'}, setup=True)
        for mock in (patch.object(mail, 'config_path', return_value=Path(temporary.name) / 'mail.bin'),
                     patch.object(mail, 'crypt', side_effect=lambda value, decrypt=False: value)):
            mock.start()
            self.addCleanup(mock.stop)
        self.configure(False)

    def configure(self, enabled):
        return mail.save(self.store, self.actor, {
            'remetente': mail.DEFAULT, 'destinatario': mail.DEFAULT,
            'senha_app': 'abcdefghijklmnop', 'mandados_automaticos': enabled,
        })

    def collect(self, number, text, version):
        self.store.import_corpus({'execucao': {'id': 'coleta-' + version}, 'processos': [{
            'processo': NUMBER, 'detalhes': {'texto': 'Nº do processo ' + NUMBER,
                'tabelas': [{'linhas': [
                    ['Evento', 'Data/Hora', 'Descrição', 'Usuário', 'Documentos'],
                    [str(number), '10/11/2026 14:15:00', text, version, 'MANDADO1'],
                ]}],
            },
        }]}, self.actor)
        mandados.scan(self.store)
        mail.process_mandates(self.store)

    @patch.object(mail, 'smtp_send')
    def test_only_new_mandate_versions_send_once(self, send):
        self.collect(1, 'Mandado expedido', 'antigo')
        send.assert_not_called()
        self.assertTrue(self.configure(True)['mandados_automaticos'])
        self.collect(1, 'Mandado expedido', 'nova-leitura')
        send.assert_not_called()
        self.collect(2, 'Pedido de expedição de mandado', 'pedido')
        self.assertEqual(send.call_count, 1)
        self.assertIn('Pedido identificado', send.call_args.args[2])
        self.collect(2, 'Pedido de expedição de mandado', 'recoleta')
        self.collect(3, 'Certidão com menção ao mandado', 'mencao')
        self.assertEqual(send.call_count, 1)
        self.collect(2, 'Mandado expedido', 'expedicao')
        self.assertEqual(send.call_count, 2)
        self.assertIn('Possível expedição', send.call_args.args[2])
        mail.process_mandates(self.store)
        self.assertEqual(send.call_count, 2)

    @patch.object(mail, 'smtp_send', side_effect=OSError('resposta perdida'))
    def test_uncertain_delivery_is_not_repeated(self, send):
        self.configure(True)
        with self.assertRaises(juridico.AppError):
            self.collect(1, 'Mandado expedido', 'evento')
        mail.process_mandates(self.store)
        self.collect(1, 'Mandado expedido', 'outra-leitura')
        send.assert_called_once()
        self.assertEqual(mail.status(self.store, self.actor)['historico'][0]['status'], 'incerto')
