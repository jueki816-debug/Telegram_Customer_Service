# Filename: rag_engine.py
import os
from pypdf import PdfReader
from rank_bm25 import BM25Okapi

class LightRAGEngine:
    def __init__(self, pdf_path="knowledge.pdf"):
        self.chunks = []
        self.bm25 = None
        self._load_and_index(pdf_path)

    def _load_and_index(self, pdf_path):
        if not os.path.exists(pdf_path):
            print(f"[Warning] {pdf_path} မတွေ့ပါ။ RAG စနစ် အလွတ်ဖြင့် ဆက်လက်အလုပ်လုပ်ပါမည်။")
            return
        
        try:
            reader = PdfReader(pdf_path)
            text = ""
            for page in reader.pages:
                extracted = page.extract_text()
                if extracted:
                    text += extracted + "\n"
            
            # စာပိုဒ်များကို တစ်ပိုဒ်ချင်းစီ ခွဲထုတ်ခြင်း (Chunking)
            raw_chunks = text.split('\n\n')
            self.chunks = [c.strip() for c in raw_chunks if len(c.strip()) > 50]
            
            if self.chunks:
                # BM25 Algorithm အတွက် စကားလုံးများခွဲခြမ်းခြင်း (Tokenization)
                tokenized_corpus = [chunk.lower().split() for chunk in self.chunks]
                self.bm25 = BM25Okapi(tokenized_corpus)
                print(f"[Success] RAG Engine: {len(self.chunks)} chunks ထည့်သွင်းပြီးပါပြီ။")
                
        except Exception as e:
            print(f"[Error] PDF ဖတ်ရှုခြင်း မအောင်မြင်ပါ: {e}")

    def retrieve(self, query, top_k=3):
        """User မေးခွန်းနှင့် အကိုက်ညီဆုံး အချက်အလက်များကို ရှာဖွေပေးခြင်း"""
        if not self.bm25 or not self.chunks:
            return "ကိုးကားရန် အချက်အလက် မရှိပါ။"
        
        tokenized_query = query.lower().split()
        # အကောင်းဆုံး ကိုက်ညီသော စာပိုဒ်များကို ဆွဲထုတ်ခြင်း
        results = self.bm25.get_top_n(tokenized_query, self.chunks, n=top_k)
        return "\n\n".join(results)