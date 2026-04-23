#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Extrator de PDF para Dashboard (Versão Multi-Obra)
Converte PDFs de Contas a Pagar em JSON e atualiza o dashboard automaticamente.
Suporta múltiplas obras (Nest, URBI/Cidade Aruna).
"""

import re
import json
from datetime import datetime
from pathlib import Path
import sys
import PyPDF2

# Tenta importar o módulo de atualização do dashboard
try:
    from atualizar_dashboard import atualizar_html_com_novos_dados
except ImportError:
    atualizar_html_com_novos_dados = None

def extrair_texto_pdf(arquivo_pdf):
    """Extrai todo o texto do PDF usando PyPDF2"""
    texto_completo = []
    
    try:
        with open(arquivo_pdf, 'rb') as f:
            pdf_reader = PyPDF2.PdfReader(f)
            # print(f"[PDF] Lendo {arquivo_pdf.name} ({len(pdf_reader.pages)} paginas)")
            
            for i, page in enumerate(pdf_reader.pages, 1):
                texto = page.extract_text()
                texto_completo.append(texto)
            
        return '\n'.join(texto_completo)
    
    except Exception as e:
        print(f"[ERRO] Erro ao ler PDF {arquivo_pdf.name}: {e}")
        return None

def merge_dados(dados_existentes, novos_dados):
    """Mescla os novos dados na estrutura existente (acumula fornecedores/obras)"""
    
    # Se lista de fornecedores estiver vazia, inicializar
    if not dados_existentes["fornecedores"]:
        dados_existentes["fornecedores"] = novos_dados["fornecedores"]
        dados_existentes["obras"] = novos_dados["obras"]
        dados_existentes["total_geral"] = novos_dados["total_geral"]
        dados_existentes["total_documentos"] = novos_dados["total_documentos"]
        dados_existentes["total_fornecedores"] = novos_dados["total_fornecedores"]
        return dados_existentes
        
    # Map existente de fornecedores para facilitar busca
    map_fornecedores = {f["fornecedor"]: f for f in dados_existentes["fornecedores"]}
    
    for novo_f in novos_dados["fornecedores"]:
        nome = novo_f["fornecedor"]
        
        if nome in map_fornecedores:
            # Fornecedor ja existe, mesclar documentos
            f_existente = map_fornecedores[nome]
            f_existente["documentos"].extend(novo_f["documentos"])
            f_existente["qtd"] += novo_f["qtd"]
            f_existente["total"] += novo_f["total"]
            
            # Atualizar datas (preserva a logica existente de string)
            pass 
        else:
            # Novo fornecedor
            dados_existentes["fornecedores"].append(novo_f)
            
    # Atualizar obras (unificando sets)
    set_obras = set(dados_existentes["obras"])
    set_obras.update(novos_dados["obras"])
    dados_existentes["obras"] = sorted(list(set_obras))
    
    # Recalcular totais gerais
    dados_existentes["total_geral"] = sum(f["total"] for f in dados_existentes["fornecedores"])
    dados_existentes["total_fornecedores"] = len(dados_existentes["fornecedores"])
    dados_existentes["total_documentos"] = sum(f["qtd"] for f in dados_existentes["fornecedores"])
    
    return dados_existentes

def processar_dados_pdf_data_vencimento(texto):
    """
    Novo parser para o relatorio Contas a Pagar (por Data de Vencimento)
    """
    dados = {
        "atualizado_em": datetime.now().strftime('%d/%m/%Y %H:%M'),
        "total_geral": 0.0,
        "total_fornecedores": 0,
        "total_documentos": 0,
        "obras": [],
        "fornecedores": []
    }
    
    linhas = texto.split('\n')
    # Removido \b do inicio para capturar tipos colados no nome do fornecedor (ex: LTDAPPC)
    KNOWN_TYPES_REGEX = r'(PRC[A-Z]+|NFE|NFSE|PPC|PCT|CAU|GPS|FAT|REC|ND|CAUCAO|NF|DOC|ADF|AV|ISS|CSRF|CF|PRV|MDC)\.*'
    
    obra_arquivo = "Indefinida"
    for linha in linhas[:20]:
        match_obra = re.search(r'(Nest\s+\d+|OBRA\s+Aruna\s+Torres|OBRA\s+\d+|Cidade\s+Aruna|Aruna\s+Torres|URBI)', linha, re.IGNORECASE)
        if match_obra:
            nome = match_obra.group(1).strip()
            if "TORRES" in nome.upper():
                obra_arquivo = "Aruna Torres"
            elif "ARUNA" in nome.upper() or "URBI" in nome.upper():
                obra_arquivo = "Cidade Aruna (URBI)"
            elif "NEST" in nome.upper():
                obra_arquivo = "Nest 635"
            else:
                obra_arquivo = nome
            break
            
    docs = []
    
    data_venc_atual = None
    fornecedor_acumulado = []
    
    for i, linha in enumerate(linhas):
        linha_clean = linha.strip()
        if not linha_clean:
            continue
            
        if "SIENGE / STARIAN" in linha: continue
        if linha.startswith("Empresa ") or linha.startswith("Obra") or linha.startswith("Período"): continue
        if linha.startswith("Juros") or linha.startswith("Após Vencto") or "Total do dia" in linha or "Total vencido no período" in linha or "Total a vencer no período" in linha or "Total da empresa" in linha:
            fornecedor_acumulado = []
            continue
            
        if linha.startswith("Contas a Pagar") or "Credor Documento Lançamento" in linha:
            continue
            
        match_data = re.search(r'^Data de vencimento\s+(\d{2}/\d{2}/\d{4})', linha)
        if match_data:
            data_venc_atual = match_data.group(1)
            fornecedor_acumulado = []
            continue
            
        if "Obs:" in linha:
            # Não limpamos o fornecedor_acumulado aqui pois a Obs vem DEPOIS do documento
            continue
            
        # Regex para capturar a linha do documento no formato "por Data de Vencimento"
        # Procura Lançamento (ddd/d ou dddd) seguido de Qt Ind etc e depois blocos de valores
        match_doc_line = re.search(r'\s+(\d+/\d+|\d+)\s+\d+\s*\d*\s*\d*\s*(?:[\d\.]*,\d{2}\s*){1,4}$', linha)
        
        if match_doc_line and data_venc_atual:
            lancamento = match_doc_line.group(1)
            # Valor total é sempre o ÚLTIMO valor formatado como dinheiro na linha
            valores_encontrados = re.findall(r'[\d\.]*,\d{2}', linha)
            if not valores_encontrados: continue
            
            valor_str = valores_encontrados[-1].replace('.', '').replace(',', '.')
            try:
                valor = float(valor_str)
            except:
                continue
                
            texto_info = linha[:match_doc_line.start()].strip()
            if fornecedor_acumulado:
                texto_info = " ".join(fornecedor_acumulado) + " " + texto_info
                fornecedor_acumulado = []
            
            # Tentar encontrar o tipo no final do texto_info
            match_tipo = re.search(KNOWN_TYPES_REGEX, texto_info, re.IGNORECASE)
            
            tipo_doc = "OUTROS"
            num_doc = "N/D"
            fornecedor = texto_info
            
            if match_tipo:
                tipo_doc = match_tipo.group(1).upper()
                if tipo_doc.startswith("PRC") and len(tipo_doc) > 3:
                    tipo_doc = tipo_doc[3:]
                    
                resto = texto_info[match_tipo.end():].strip()
                num_doc = resto.strip("- ")
                if not num_doc: num_doc = "N/D"
                
                # Fornecedor é o que vem antes do tipo
                fornecedor = texto_info[:match_tipo.start()].strip()
            else:
                # Se não achou tipo conhecido, tenta separar por espaço, ultima palavra documento
                partes = texto_info.split()
                if(len(partes) > 1 and (partes[-1].isdigit() or '/' in partes[-1])):
                    num_doc = partes[-1]
                    fornecedor = " ".join(partes[:-1])
            
            # --- LIMPEZA ADICIONAL DO FORNECEDOR ---
            # Remove cabeçalhos que possam ter grudado
            fornecedor = re.sub(r'venctoAcréscimo Desconto Total\s*', '', fornecedor).strip()
            fornecedor = re.sub(r'venctoAcrscimo Desconto Total\s*', '', fornecedor).strip()
            fornecedor = re.sub(r'Credor Documento Lançamento\s*', '', fornecedor).strip()
            
            # Remove valores de carry-over que ficam no início (ex: "868,46 EVEHX")
            fornecedor = re.sub(r'^[\d\.,\s-]+(?=[A-Z])', '', fornecedor).strip()
            
            # Limpeza final
            fornecedor = re.sub(r'^[\W_]+', '', fornecedor)
            fornecedor = fornecedor.rstrip(' -').strip()
            
            if not fornecedor: nome_fornecedor = "Desconhecido"
            else: nome_fornecedor = fornecedor

            
            try:
                hoje = datetime.now()
                dias_diff = (datetime.strptime(data_venc_atual, '%d/%m/%Y') - hoje).days
                if dias_diff < 0: status = "Vencido"
                elif dias_diff <= 30: status = "A vencer (até 30 dias)"
                else: status = "A vencer (acima de 30 dias)"
            except:
                status = "A vencer (acima de 30 dias)"
                
            doc_obj = {
                "documento": num_doc,
                "lancamento": lancamento,
                "tipo": tipo_doc,
                "vencimento": data_venc_atual,
                "valor": valor,
                "status": status,
                "obra": obra_arquivo
            }
            docs.append((nome_fornecedor, doc_obj))
        else:
            if not "Total do dia" in linha:
                 fornecedor_acumulado.append(linha_clean)
                 
    # Agrupar docs por fornecedor
    fornecedores_map = {}
    for forn, doc_obj in docs:
        if forn not in fornecedores_map:
            fornecedores_map[forn] = {
                "fornecedor": forn, "qtd": 0, "total": 0.0,
                "proximo": doc_obj["vencimento"], "distante": doc_obj["vencimento"],
                "documentos": []
            }
        f_obj = fornecedores_map[forn]
        f_obj["documentos"].append(doc_obj)
        f_obj["qtd"] += 1
        f_obj["total"] += doc_obj["valor"]
        
    dados["fornecedores"] = list(fornecedores_map.values())
    dados["total_geral"] = sum(f["total"] for f in dados["fornecedores"])
    dados["total_fornecedores"] = len(dados["fornecedores"])
    dados["total_documentos"] = sum(f["qtd"] for f in dados["fornecedores"])
    dados["obras"] = [obra_arquivo] if obra_arquivo != "Indefinida" else []
    
    return dados


def processar_dados_pdf(texto):
    # Detecta qual é o tipo de relatório gerado
    if "por Data de Vencimento" in texto[:500]:
        return processar_dados_pdf_data_vencimento(texto)
    """
    Processa o texto extraido e converte em estrutura JSON.
    Adaptado para identificar obras Nest e URBI/Cidade Aruna.
    """
    
    dados = {
        "atualizado_em": datetime.now().strftime('%d/%m/%Y %H:%M'),
        "total_geral": 0.0,
        "total_fornecedores": 0,
        "total_documentos": 0,
        "obras": [],
        "fornecedores": []
    }
    
    linhas = texto.split('\n')
    fornecedor_atual = None
    obras_set = set()
    fornecedores_map = {}
    
    # Lista de prefixos de documentos conhecidos
    KNOWN_TYPES_REGEX = r'\b(PRC[A-Z]+|NFE|NFSE|PPC|PCT|CAU|GPS|FAT|REC|ND|CAUCAO|NF|DOC)\.?'
    
    # Linhas para ignorar/pular
    SKIP_PREFIXES = [
        "Credor Centro", "Contas a Pagar", "Período", "SIENGE", "Total do credor", 
        "Obs:", "Empresa", "Data do", "Juros", "Após Vencto",
        "PAGO", "PAGA", "NF ", "VERIFICAR", "RETENCAO", "REFERENTE"
    ]
    
    # Regex expandida para capturar Nest e URBI
    REGEX_OBRA = r'(Nest\s+\d+|OBRA\s+Aruna\s+Torres|OBRA\s+\d+|Cidade\s+Aruna|Aruna\s+Torres|URBI\s+\-\s+Custos|URBI)'
    
    for i, linha in enumerate(linhas):
        linha_clean = linha.strip()
        if not linha_clean:
            continue
            
        # Pular cabeçalhos simples
        if "Credor Centro de custo" in linha: continue
        if "Contas a Pagar" in linha: continue
        if linha.startswith("Período"): continue
        if "SIENGE / STARIAN" in linha: continue
        if "Total do credor" in linha: continue
        if "Obs:" in linha: continue
        if linha_clean.startswith("Empresa") and ("PRC Empreendimentos" in linha or "XR Aruna Torres" in linha or "Empreendimentos" in linha): continue
        
        # 1. Tentar identificar Obra e Fornecedor
        if "Nest 635" in linha or "OBRA" in linha.upper() or "ARUNA" in linha.upper() or "URBI" in linha.upper() or "TORRES" in linha.upper():
            match_cc = re.search(REGEX_OBRA, linha, re.IGNORECASE)
            
            if match_cc:
                # -------------------------
                # Identificou Obra
                # -------------------------
                nome_obra_raw = match_cc.group(1).strip()
                
                # Normaliza o nome da obra para uso no Dashboard
                if "TORRES" in nome_obra_raw.upper():
                    obra_atual = "Aruna Torres"
                elif "ARUNA" in nome_obra_raw.upper() or "URBI" in nome_obra_raw.upper():
                    obra_atual = "Cidade Aruna (URBI)"
                elif "NEST" in nome_obra_raw.upper():
                    obra_atual = "Nest 635"
                else:
                    obra_atual = nome_obra_raw
                    
                obras_set.add(obra_atual)
                
                # O texto ANTES do match da obra é potencialmente o fornecedor
                inicio_cc = match_cc.start()
                possivel_fornecedor = linha[:inicio_cc].strip()
                
                # --- Tratamento de nome composto (múltiplas linhas anteriores) ---
                # Verifica até 2 linhas anteriores para capturar nomes quebrados
                if i > 0:
                    linha_ant = linhas[i-1].strip()
                    eh_lixo = any(p in linha_ant for p in SKIP_PREFIXES)
                    eh_data_pag = re.search(r'\d+ de \d+', linha_ant)
                    tem_obra = re.search(REGEX_OBRA, linha_ant, re.IGNORECASE)
                    
                    # Se a linha anterior é válida e não tem obra, pode ser parte do nome
                    if not eh_lixo and not eh_data_pag and not tem_obra and len(linha_ant) > 3:
                        if not possivel_fornecedor:
                             # Se a linha atual começa com a Obra, o fornecedor está todo na linha de cima
                             possivel_fornecedor = linha_ant
                        else:
                             # Se tem pedaço na linha atual, junta com a anterior
                             possivel_fornecedor = linha_ant + " " + possivel_fornecedor
                        
                        # Verifica se há uma segunda linha anterior também válida
                        if i > 1:
                            linha_ant2 = linhas[i-2].strip()
                            eh_lixo2 = any(p in linha_ant2 for p in SKIP_PREFIXES)
                            eh_data_pag2 = re.search(r'\d+ de \d+', linha_ant2)
                            tem_obra2 = re.search(REGEX_OBRA, linha_ant2, re.IGNORECASE)
                            
                            if not eh_lixo2 and not eh_data_pag2 and not tem_obra2 and len(linha_ant2) > 3:
                                possivel_fornecedor = linha_ant2 + " " + possivel_fornecedor
                
                # Validar e processar fornecedor
                if (possivel_fornecedor and 
                    len(possivel_fornecedor) > 3 and 
                    not re.match(r'^\d+$', possivel_fornecedor) and 
                    "Empresa" not in possivel_fornecedor and 
                    "Obra82" not in possivel_fornecedor):
                    
                    nome_fornecedor = possivel_fornecedor.strip()
                    
                    # ===== LIMPEZA RIGOROSA DO NOME DO FORNECEDOR =====
                    # Remove caracteres estranhos do inicio
                    nome_fornecedor = re.sub(r'^[\W_]+', '', nome_fornecedor)
                    
                    # Remove qualquer texto relacionado à obra que possa ter colado
                    # Padrões: "Cidade Aruna - Itororó - Lote 07 - Studio", "URBI - Custos Obra", etc
                    nome_fornecedor = re.sub(r'Cidade\s+Aruna.*$', '', nome_fornecedor, flags=re.IGNORECASE).strip()
                    nome_fornecedor = re.sub(r'URBI\s*-\s*Custos.*$', '', nome_fornecedor, flags=re.IGNORECASE).strip()
                    nome_fornecedor = re.sub(r'Nest\s+\d+.*$', '', nome_fornecedor, flags=re.IGNORECASE).strip()
                    nome_fornecedor = re.sub(r'OBRA\s+Aruna\s+Torres.*$', '', nome_fornecedor, flags=re.IGNORECASE).strip()
                    nome_fornecedor = re.sub(r'Aruna\s+Torres.*$', '', nome_fornecedor, flags=re.IGNORECASE).strip()
                    nome_fornecedor = re.sub(r'Itororó.*$', '', nome_fornecedor, flags=re.IGNORECASE).strip()
                    nome_fornecedor = re.sub(r'Lote\s+\d+.*$', '', nome_fornecedor, flags=re.IGNORECASE).strip()
                    nome_fornecedor = re.sub(r'Studio.*$', '', nome_fornecedor, flags=re.IGNORECASE).strip()
                    
                    # Remove traços/hifens soltos no final
                    nome_fornecedor = nome_fornecedor.rstrip(' -').strip()
                    
                    # ===== VALIDAÇÕES FINAIS =====
                    # Se após limpeza ficou vazio ou muito curto, pular
                    if len(nome_fornecedor) < 3:
                        continue
                    
                    # Rejeitar se começar com código de documento (PRC, NFE, etc)
                    if re.match(r'^(PRC|NFE|NFSE|PPC|PCT|CAU|GPS|FAT|REC|ND|CAUCAO)', nome_fornecedor, re.IGNORECASE):
                        continue
                    
                    # Rejeitar se for apenas números e pontos/barras
                    if re.match(r'^[\d\s\.\-/]+$', nome_fornecedor):
                        continue
                    
                    # Rejeitar instruções de pagamento (PIX, banco, etc)
                    if any(palavra in nome_fornecedor.upper() for palavra in ['PGTO:', 'PIX', 'BANCO', 'PARCELA', 'AG:', 'CC:']):
                        continue
                    
                    # Rejeitar referências a obras que passaram pela limpeza
                    if re.match(r'^(Obra|OBRA)\d+', nome_fornecedor, re.IGNORECASE):
                        continue
                    
                    if nome_fornecedor in fornecedores_map:
                        fornecedor_atual = fornecedores_map[nome_fornecedor]
                    else:
                        fornecedor_atual = {
                            "fornecedor": nome_fornecedor,
                            "qtd": 0,
                            "total": 0.0,
                            "proximo": "",
                            "distante": "",
                            "documentos": []
                        }
                        fornecedores_map[nome_fornecedor] = fornecedor_atual
                        dados["fornecedores"].append(fornecedor_atual)
        
        # 2. Tentar identificar Documento (Data e Valor)
        # Padrao: (possivel numero)(dd/mm/aaaa) (espacos) (valores)
        # Pega a data e o resto da string para encontrar o ÚLTIMO valor (Total)
        match_doc_line = re.search(r'(\d*)(\d{2}/\d{2}/\d{4})\s+\d*\s+(.*)', linha)
        
        if match_doc_line and fornecedor_atual:
            vencimento = match_doc_line.group(2)
            valores_str = match_doc_line.group(3)
            
            # Extrai todos os valores formatados como dinheiro (ex: 1.234,56 ou 0,00)
            valores_encontrados = re.findall(r'[\d\.]*,\d{2}', valores_str)
            if not valores_encontrados:
                continue
                
            # O último valor da linha é sempre o Total (após Acréscimo e Desconto)
            valor_str = valores_encontrados[-1].replace('.', '').replace(',', '.')

            
            try:
                valor = float(valor_str)
            except:
                continue

            # Logica de Status
            try:
                data_venc = datetime.strptime(vencimento, '%d/%m/%Y')
                hoje = datetime.now()
                dias_diff = (data_venc - hoje).days
                if dias_diff < 0:
                    status = "Vencido"
                elif dias_diff <= 30:
                    status = "A vencer (até 30 dias)"
                else:
                    status = "A vencer (acima de 30 dias)"
            except:
                status = "A vencer (acima de 30 dias)"
            
            # --- Tentar extrair Detalhes do Documento ---
            # Corta a string até a data encontrada
            index_data = linha.find(match_doc_line.group(0))
            texto_info = linha[:index_data].strip()
            
            # Se a linha contem Obra, remove a parte da obra para isolar o documento
            # Ex: ... Nest 635 ... [DOC]
            if "Nest 635" in texto_info:
                 match_obra = re.search(r'Nest 635.*?-', texto_info)
                 if match_obra: texto_info = texto_info[match_obra.end():].strip()
            elif "Aruna Torres" in texto_info:
                 match_obra = re.search(r'Aruna Torres.*?-', texto_info)
                 if match_obra: texto_info = texto_info[match_obra.end():].strip()
            elif "URBI" in texto_info:
                 match_obra = re.search(r'URBI.*?-', texto_info)
                 if match_obra: texto_info = texto_info[match_obra.end():].strip()
            
            # Remove "Custos Obra" ou "Custos Incorporadora" que podem estar colados no tipo do doc
            texto_info = re.sub(r'Custos\s+Obra\s*', '', texto_info, flags=re.IGNORECASE).strip()
            texto_info = re.sub(r'Custos\s+Incorporadora\s*', '', texto_info, flags=re.IGNORECASE).strip()
            
            tipo_doc = "OUTROS"
            num_doc = "N/D"
            lancamento = "---"
            
            # Identificar Tipo (adicionamos novos tipos: ADF, AV, ISS, CSRF, CF)
            KNOWN_TYPES_REGEX_UPDATED = r'\b(PRC[A-Z]+|NFE|NFSE|PPC|PCT|CAU|GPS|FAT|REC|ND|CAUCAO|NF|DOC|ADF|AV|ISS|CSRF|CF)\.?'
            match_tipo = re.search(KNOWN_TYPES_REGEX_UPDATED, texto_info, re.IGNORECASE)
            if match_tipo:
                tipo_doc = match_tipo.group(1).upper()
                if tipo_doc.startswith("PRC") and len(tipo_doc) > 3:
                    tipo_doc = tipo_doc[3:]
                    
                texto_sem_tipo = texto_info[match_tipo.end():].strip()
                
                # Tentar separar Numero Doc de Lancamento
                palavras = texto_sem_tipo.split()
                if palavras:
                    possivel_lancamento = palavras[-1]
                    if '/' in possivel_lancamento or (possivel_lancamento.isdigit() and len(possivel_lancamento) > 3):
                        lancamento = possivel_lancamento
                        num_doc = " ".join(palavras[:-1])
                    else:
                        num_doc = " ".join(palavras)
                
                num_doc = num_doc.strip("- ")
                if not num_doc: num_doc = "N/D"
                
                # Limpa lancamento se tiver colado prefixo
                match_clean_lanc = re.search(r'(\d+/\d+|\d+)$', lancamento)
                if match_clean_lanc:
                    lancamento = match_clean_lanc.group(1)

            documento = {
                "documento": num_doc,
                "lancamento": lancamento,
                "tipo": tipo_doc,
                "vencimento": vencimento,
                "valor": valor,
                "status": status,
                "obra": obra_atual if 'obra_atual' in locals() else "Indefinida"
            }
            
            # Adiciona ao fornecedor corrente
            fornecedor_atual["documentos"].append(documento)
            fornecedor_atual["qtd"] += 1
            fornecedor_atual["total"] += valor
            
            # Atualiza datas de referencia (proximo/distante)
            if not fornecedor_atual["proximo"]: fornecedor_atual["proximo"] = vencimento
            if not fornecedor_atual["distante"]: fornecedor_atual["distante"] = vencimento

    # Finaliza calculos
    dados["total_geral"] = sum(f["total"] for f in dados["fornecedores"])
    dados["total_fornecedores"] = len(dados["fornecedores"])
    dados["total_documentos"] = sum(f["qtd"] for f in dados["fornecedores"])
    dados["obras"] = sorted(list(obras_set))
    
    return dados

def salvar_json(dados, caminho):
    try:
        with open(caminho, 'w', encoding='utf-8') as f:
            json.dump(dados, f, ensure_ascii=False, indent=2)
        print(f"[OK] JSON salvo em: {caminho.name}")
        return True
    except Exception as e:
        print(f"[ERRO] Falha ao salvar JSON: {e}")
        return False

def main():
    print("=" * 70)
    print("     EXTRATOR DE PDF MULTI-OBRA")
    print("=" * 70)
    
    script_dir = Path(__file__).parent
    
    # 1. Encontrar PDFs
    pdfs = list(script_dir.glob('*.pdf'))
    if not pdfs:
        print("[ERRO] Nenhum PDF encontrado.")
        return

    print(f"[INFO] Encontrados {len(pdfs)} arquivos PDF.")
    
    # 2. Inicializar Estrutura Unificada
    dados_finais = {
        "atualizado_em": datetime.now().strftime('%d/%m/%Y %H:%M'),
        "total_geral": 0.0,
        "total_fornecedores": 0,
        "total_documentos": 0,
        "obras": [],
        "fornecedores": []
    }
    
    # 3. Processar cada PDF e acumular dados
    for pdf in pdfs:
        print(f"   -> Processando: {pdf.name}...")
        texto = extrair_texto_pdf(pdf)
        if texto:
            dados_pdf = processar_dados_pdf(texto)
            print(f"      [OK] {dados_pdf['total_documentos']} docs, {len(dados_pdf['obras'])} obras")
            
            # Mesclar
            dados_finais = merge_dados(dados_finais, dados_pdf)
    
    print("-" * 70)
    print("RESUMO CONSOLIDADO:")
    print(f"   Total Geral: R$ {dados_finais['total_geral']:,.2f}")
    print(f"   Docs: {dados_finais['total_documentos']}")
    print(f"   Obras: {', '.join(dados_finais['obras'])}")
    print("-" * 70)
    
    # 4. Salvar JSON
    json_path = script_dir / 'dados_atualizados.json'
    if salvar_json(dados_finais, json_path):
        
        # 5. Atualizar Dashboard
        if atualizar_html_com_novos_dados:
            print("[INFO] Atualizando dashboard HTML...")
            html_path = script_dir / 'dashboard_v_final.html'
            try:
                atualizar_html_com_novos_dados(str(html_path), dados_finais)
                print("[SUCESSO] Dashboard atualizado!")
            except Exception as e:
                print(f"[ERRO] Falha ao atualizar HTML: {e}")
        else:
            print("[AVISO] Script 'atualizar_dashboard.py' nao importado. Dashboard nao atualizado.")

if __name__ == "__main__":
    main()
