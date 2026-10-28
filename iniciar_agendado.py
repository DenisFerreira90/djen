"""Inicia o serviço local se ainda não estiver acessível; não duplica servidor."""
import os
from pathlib import Path
import subprocess
import sys
from urllib.request import urlopen

if __name__=='__main__':
    port=int(os.environ.get('DJEN_PORT','8765'))
    try:
        with urlopen('http://127.0.0.1:'+str(port)+'/api/health',timeout=3) as response:running=response.status==200
    except Exception:running=False
    if not running:subprocess.Popen([sys.executable,str(Path(__file__).with_name('servidor.py')),'--sem-navegador'],cwd=str(Path(__file__).parent))
