#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Dashboard Contas a Pagar - Servidor Local com Log
Duplo clique para abrir o dashboard no navegador.
Processa PDFs do Sienge usando PyPDF2 no servidor.
Registra acessos e uploads em dashboard_log.txt.
"""

import http.server
import json
import os
import sys
import re
import socket
import webbrowser
import threading
import logging
from pathlib import Path
from datetime import datetime

# Import the PDF extraction logic
sys.path.insert(0, str(Path(__file__).parent))
from extrair_pdf_para_dashboard import extrair_texto_pdf, processar_dados_pdf, merge_dados

PORT = 8080
SCRIPT_DIR = Path(__file__).parent
LOG_FILE = SCRIPT_DIR / 'dashboard_log.txt'

# ========== LOGGING SETUP ==========
logger = logging.getLogger('dashboard')
logger.setLevel(logging.INFO)

# File handler (persiste em disco)
fh = logging.FileHandler(LOG_FILE, encoding='utf-8')
fh.setFormatter(logging.Formatter('%(asctime)s | %(message)s', datefmt='%d/%m/%Y %H:%M:%S'))
logger.addHandler(fh)

# Console handler (mostra no terminal)
ch = logging.StreamHandler()
ch.setFormatter(logging.Formatter('  %(message)s'))
logger.addHandler(ch)


def resolve_hostname(ip):
    """Tenta resolver o nome da maquina a partir do IP."""
    try:
        hostname = socket.gethostbyaddr(ip)[0]
        return hostname
    except:
        return ip


class DashboardHandler(http.server.SimpleHTTPRequestHandler):
    """HTTP handler that serves dashboard files and processes PDF uploads."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(SCRIPT_DIR), **kwargs)

    def do_GET(self):
        """Serve files and log page accesses."""
        client_ip = self.client_address[0]
        path = self.path.split('?')[0]

        # Log only meaningful page accesses (not static assets)
        if path.endswith('.html') or path == '/':
            hostname = resolve_hostname(client_ip)
            logger.info(f"ACESSO  | IP: {client_ip} ({hostname}) | Pagina: {path}")

        super().do_GET()

    def do_POST(self):
        """Handle PDF upload and extraction."""
        client_ip = self.client_address[0]
        hostname = resolve_hostname(client_ip)

        if self.path == '/api/extract':
            try:
                content_type = self.headers.get('Content-Type', '')
                if 'multipart/form-data' not in content_type:
                    self._send_json(400, {'error': 'Expected multipart/form-data'})
                    return

                boundary = content_type.split('boundary=')[1].encode()
                content_length = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(content_length)
                files = self._parse_multipart(body, boundary)

                if not files:
                    self._send_json(400, {'error': 'Nenhum arquivo recebido'})
                    return

                # Log upload
                file_names = [f[0] for f in files]
                total_size_kb = sum(len(f[1]) for f in files) / 1024
                logger.info(f"UPLOAD  | IP: {client_ip} ({hostname}) | Arquivos: {', '.join(file_names)} | Tamanho: {total_size_kb:.0f} KB")

                # Process each file
                dados_finais = {
                    "atualizado_em": datetime.now().strftime('%d/%m/%Y %H:%M'),
                    "total_geral": 0.0,
                    "total_fornecedores": 0,
                    "total_documentos": 0,
                    "obras": [],
                    "fornecedores": []
                }

                processed_files = []
                for filename, file_data in files:
                    if filename.lower().endswith('.pdf'):
                        tmp_path = SCRIPT_DIR / f'_tmp_{filename}'
                        try:
                            with open(tmp_path, 'wb') as f:
                                f.write(file_data)
                            texto = extrair_texto_pdf(tmp_path)
                            if texto:
                                dados_pdf = processar_dados_pdf(texto)
                                dados_finais = merge_dados(dados_finais, dados_pdf)
                                processed_files.append(filename)
                        finally:
                            if tmp_path.exists():
                                tmp_path.unlink()

                    elif filename.lower().endswith('.json'):
                        data = json.loads(file_data.decode('utf-8'))
                        if 'fornecedores' in data:
                            dados_finais = merge_dados(dados_finais, data)
                            processed_files.append(filename)

                if not processed_files:
                    logger.info(f"ERRO    | IP: {client_ip} ({hostname}) | Nenhum dado extraido dos arquivos")
                    self._send_json(400, {'error': 'Nenhum arquivo válido processado'})
                    return

                # Log success
                n_forn = dados_finais.get('total_fornecedores', 0)
                n_docs = dados_finais.get('total_documentos', 0)
                total = dados_finais.get('total_geral', 0)
                logger.info(f"SUCESSO | IP: {client_ip} ({hostname}) | {n_forn} fornecedores, {n_docs} docs, R$ {total:,.2f}")

                result = {
                    'success': True,
                    'files': processed_files,
                    'data': dados_finais
                }
                self._send_json(200, result)

            except Exception as e:
                logger.info(f"ERRO    | IP: {client_ip} ({hostname}) | {str(e)}")
                self._send_json(500, {'error': f'Erro ao processar: {str(e)}'})
                import traceback
                traceback.print_exc()
        else:
            self._send_json(404, {'error': 'Not found'})

    def _parse_multipart(self, body, boundary):
        """Simple multipart parser to extract files."""
        files = []
        parts = body.split(b'--' + boundary)
        for part in parts:
            if b'filename="' not in part:
                continue
            header_end = part.find(b'\r\n\r\n')
            if header_end < 0:
                continue
            header = part[:header_end].decode('utf-8', errors='ignore')
            file_data = part[header_end + 4:]
            if file_data.endswith(b'\r\n'):
                file_data = file_data[:-2]
            if file_data.endswith(b'--'):
                file_data = file_data[:-2]
            if file_data.endswith(b'\r\n'):
                file_data = file_data[:-2]
            match = re.search(r'filename="([^"]+)"', header)
            if match:
                filename = match.group(1)
                files.append((filename, file_data))
        return files

    def _send_json(self, status, data):
        """Send JSON response."""
        response = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', len(response))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(response)

    def do_OPTIONS(self):
        """Handle CORS preflight."""
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def log_message(self, format, *args):
        """Suppress default HTTP logs (we have our own logger)."""
        pass


def get_local_ip():
    """Descobre o IP da maquina na rede local."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "seu-ip-local"


def get_hostname():
    """Descobre o nome da maquina."""
    try:
        return socket.gethostname()
    except:
        return "desconhecido"


def main():
    local_ip = get_local_ip()
    hostname = get_hostname()

    print()
    print("=" * 64)
    print("  🚀 DASHBOARD CONTAS A PAGAR - SERVIDOR ATIVO")
    print("=" * 64)
    print(f"  SUA MAQUINA:   {hostname} ({local_ip})")
    print(f"  PARA VOCE:     http://localhost:{PORT}/dashboard.html")
    print(f"  PARA EQUIPE:   http://{local_ip}:{PORT}/dashboard.html")
    print(f"                 http://{hostname}:{PORT}/dashboard.html")
    print("-" * 64)
    print(f"  📋 LOG:        {LOG_FILE}")
    print("-" * 64)
    print("  ACESSOS E UPLOADS:")
    print()

    logger.info(f"SERVIDOR INICIADO | Maquina: {hostname} ({local_ip}) | Porta: {PORT}")

    server = http.server.HTTPServer(('0.0.0.0', PORT), DashboardHandler)

    def open_browser():
        webbrowser.open(f'http://localhost:{PORT}/dashboard.html')

    threading.Timer(1.5, open_browser).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("SERVIDOR ENCERRADO")
        print("\n  Servidor encerrado.")
        server.shutdown()


if __name__ == '__main__':
    main()
