from fpdf import FPDF
from datetime import datetime

class SiengePDF(FPDF):
    def header(self):
        self.set_font('Courier', 'B', 8)
        self.cell(0, 5, 'SIENGE / STARIAN - RELATORIO DE CONTAS A PAGAR (DEMO)', 0, 1, 'L')
        self.set_font('Courier', '', 7)
        self.cell(0, 5, f'Data: {datetime.now().strftime("%d/%m/%Y")} 12:00', 0, 1, 'L')
        self.cell(0, 5, 'Empresa: 01 - CONSTRUTORA ALPHA E OMEGA LTDA', 0, 1, 'L')
        self.cell(0, 5, 'Obra: 001 - NEST 635 / CIDADE ARUNA', 0, 1, 'L')
        self.ln(5)

def criar_pdf():
    # Usar Courier para garantir alinhamento de texto fixo (estilo Sienge)
    pdf = SiengePDF()
    pdf.add_page()
    pdf.set_font('Courier', '', 8)
    
    pdf.cell(0, 5, 'Contas a Pagar por Data de Vencimento', 0, 1, 'C')
    pdf.ln(5)
    
    # Cabeçalho da tabela
    pdf.set_font('Courier', 'B', 7)
    pdf.cell(0, 5, 'Credor                          Documento     Lanc.  Acrsc.   Desc.      Total', 0, 1, 'L')
    pdf.cell(0, 5, '-' * 85, 0, 1, 'L')
    
    dados = [
        {"venc": "10/05/2026", "credor": "META ESTRUTURAS METALICAS", "doc": "NFE-445", "val": "15.300,50"},
        {"venc": "10/05/2026", "credor": "SOLARIS FACHADAS LTDA", "doc": "NFE-992", "val": "45.000,00"},
        {"venc": "15/05/2026", "credor": "CONSTRUTORA ALPHA E OMEGA", "doc": "PCT-001", "val": "120.000,00"},
        {"venc": "20/06/2026", "credor": "PEDRO BRASIL ENGENHARIA", "doc": "NFSE-12", "val": "8.500,00"},
        {"venc": "25/06/2026", "credor": "RISSI FACHADAS (DEMO)", "doc": "NFE-881", "val": "32.400,00"},
    ]
    
    current_venc = ""
    for item in dados:
        if item["venc"] != current_venc:
            pdf.ln(2)
            pdf.set_font('Courier', 'B', 8)
            pdf.cell(0, 5, f'Data de vencimento   {item["venc"]}', 0, 1, 'L')
            current_venc = item["venc"]
            
        pdf.set_font('Courier', '', 8)
        # Formatação simulada de colunas fixas
        line = f'   {item["credor"][:30]:<30} {item["doc"]:<13} 445/1    0,00    0,00   {item["val"]:>10}'
        pdf.cell(0, 5, line, 0, 1, 'L')

    output_path = "RELATORIO_SIENGE_TESTE.pdf"
    pdf.output(output_path)
    print(f"PDF gerado com sucesso: {output_path}")

if __name__ == "__main__":
    criar_pdf()
