import streamlit as st
import pdfplumber
import google.generativeai as genai
import pandas as pd
import numpy as np
import io
import requests
import re
from datetime import datetime

# DuckDuckGo 라이브러리 로드
try:
    from duckduckgo_search import DDGS
    ddgs_available = True
except ImportError:
    ddgs_available = False

# ==========================================
# 0. 안전한 Secrets 호출 함수 
# ==========================================
def get_secret(key, default=""):
    try:
        return st.secrets[key]
    except Exception:
        return default

APP_PASSWORD = "1234" 
GSHEET_CSV_URL = get_secret("GSHEET_CSV_URL", "")
GSHEET_WEBAPP_URL = get_secret("GSHEET_WEBAPP_URL", "")
GEMINI_API_KEY = get_secret("GEMINI_API_KEY", "")

st.set_page_config(page_title="NEIS 세특 AI 어시스턴트", layout="wide")

# ==========================================
# 1. 로그인 로직
# ==========================================
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.title("🔒 교과세특 AI 어시스턴트 로그인")
    pwd_input = st.text_input("비밀번호", type="password")
    if st.button("입장하기", type="primary"):
        if pwd_input == APP_PASSWORD:
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("⚠️ 비밀번호가 틀렸습니다.")
    st.stop()

# ==========================================
# 2. AI 설정 및 세션 초기화
# ==========================================
if not GEMINI_API_KEY:
    st.error("⚠️ Secrets 설정 오류: GEMINI_API_KEY가 입력되지 않았습니다.")
    st.stop()

try:
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel("gemini-2.5-flash")
    embed_model = "models/text-embedding-004" 
except Exception as e:
    st.error(f"⚠️ 구글 AI 초기화 오류: {e}")
    st.stop()

if "db_texts" not in st.session_state: st.session_state.db_texts = []
if "db_embeddings" not in st.session_state: st.session_state.db_embeddings = []
if "current_result" not in st.session_state: st.session_state.current_result = ""
if "current_template" not in st.session_state: st.session_state.current_template = ""
if "target_bytes" not in st.session_state: st.session_state.target_bytes = 1500

def get_byte_length(text): return len(text.encode('utf-8'))

# ==========================================
# 3. 구글 시트 동기화 (읽기)
# ==========================================
def sync_with_gsheet():
    if not GSHEET_CSV_URL: return 0
    try:
        response = requests.get(GSHEET_CSV_URL)
        df = pd.read_csv(io.StringIO(response.text))
        
        if not df.empty and len(df.columns) > 0:
            texts = df.iloc[:, 0].dropna().astype(str).tolist()
            if texts:
                texts = texts[:100] 
                result = genai.embed_content(model=embed_model, content=texts)
                st.session_state.db_texts = texts
                st.session_state.db_embeddings = result['embedding']
                return len(texts)
        return 0
    except Exception as e:
        return 0

# ==========================================
# 4. 화면 구성 및 사이드바
# ==========================================
st.title("📝 NEIS 세특 AI 어시스턴트 (V34: 문장 단위 절삭판)")

with st.sidebar:
    st.header("📝 기본 정보")
    subject = st.text_input("과목명", placeholder="예: 미적분")
    grade_level = st.text_input("성취도/등급", placeholder="예: A")

    st.divider()
    st.header("📏 세특 분량 설정")
    target_bytes = st.slider("목표 절대 최대치 (Bytes)", min_value=500, max_value=1500, value=1500, step=100)
    st.session_state.target_bytes = target_bytes
    
    st.divider()
    st.header("🧠 AI 지식 저장소 (선택)")
    db_file = st.file_uploader("지식 추가 (Excel/PDF)", type=["xlsx", "pdf"])
    
    if db_file and st.button("💾 구글 시트에 영구 누적하기", use_container_width=True):
        with st.spinner("지식을 동기화 중입니다..."):
            new_texts = []
            try:
                if db_file.name.endswith('.xlsx'):
                    df = pd.read_excel(db_file)
                    if not df.empty and len(df.columns) > 0:
                        new_texts = df.iloc[:, 0].dropna().astype(str).tolist()
                elif db_file.name.endswith('.pdf'):
                    with pdfplumber.open(db_file) as pdf:
                        extracted = [pg.extract_text() for pg in pdf.pages if pg.extract_text()]
                        full_pdf_text = "".join(extracted)
                        if full_pdf_text.strip():
                            new_texts = [full_pdf_text]
                
                if new_texts and GSHEET_WEBAPP_URL:
                    response = requests.post(GSHEET_WEBAPP_URL, json={"texts": new_texts})
                    if response.status_code == 200:
                        st.success("✅ 지식 저장 완료!")
                        sync_with_gsheet()
            except Exception as e:
                st.error("에러 발생")

# ==========================================
# 메인 화면: 교사 관찰 및 평가
# ==========================================
st.subheader("👨‍🏫 교사 관찰 및 평가")
col1, col2 = st.columns(2)

with col1:
    report_eval = st.text_area(
        "📄 활동/탐구 역량 평가 (비워두면 AI 자동 분석)", 
        placeholder="보고서의 팩트는 AI가 추출합니다. 특별히 강조하고 싶은 [교사 평가]가 있다면 적어주세요.", 
        height=180
    )

with col2:
    general_eval = st.text_area(
        "🧑‍🏫 교사의 인지적/인성 평가", 
        placeholder="학생의 인지적 특성과 인성적 측면에 대한 종합 평가를 적어주세요. 마지막 결론으로 융합됩니다.", 
        height=180
    )

pdf_files = st.file_uploader("학생 보고서 (PDF) - 여러 개 선택 가능", type=["pdf"], accept_multiple_files=True)

if st.session_state.authenticated and not st.session_state.db_texts and GSHEET_CSV_URL:
    sync_with_gsheet()

# ==========================================
# 5. 생성 엔진
# ==========================================
if st.button("🚀 세특 초안 생성하기", type="primary", use_container_width=True):
    if not subject:
        st.warning("👈 과목명을 입력해주세요.")
    else:
        with st.spinner("1/4: 학생 데이터를 분석 중입니다..."):
            student_report_text = ""
            if pdf_files:
                for idx, file in enumerate(pdf_files):
                    try:
                        with pdfplumber.open(file) as pdf:
                            report_content = ""
                            for pg in pdf.pages:
                                text = pg.extract_text()
                                if text: report_content += text + "\n"
                            student_report_text += f"\n--- [보고서 {idx+1}] ---\n{report_content}"
                    except Exception: pass
            
            has_report = bool(student_report_text.strip())
            if not has_report:
                student_report_text = "제출된 추가 보고서 없음"
            
        with st.spinner("2/4: 최신 동향 검색 중..."):
            trend = "검색 생략"
            if ddgs_available and has_report:
                try:
                    kw_p = f"다음 내용에서 핵심 검색어 1개만 출력: {report_eval} {student_report_text[:500]}"
                    kw_resp = model.generate_content(kw_p)
                    if kw_resp.parts:
                        kw = kw_resp.text.strip()
                        results = list(DDGS().text(f"{kw} 최신 동향", max_results=1))
                        if results: trend = results[0].get('body', '정보 없음')
                except Exception: pass

        with st.spinner("3/4: 입체적 뼈대 설계 중..."):
            guidelines = "\n".join(st.session_state.db_texts) if st.session_state.db_texts else "객관적이고 건조한 문체."
            
            bp_prompt = f"""
            당신은 최고의 고등학교 {subject} 교사입니다.
            [관찰 가능한 행동 동사] 내면 상태('이해함', '체득함') 절대 금지. 능동적 행동('증명함', '분석함')으로 우회하세요.
            [공통 가이드라인] {guidelines}
            위 규칙을 지켜 '{subject}' 과목의 세특 뼈대를 단일 문단으로 가상으로 작성하세요.
            """
            best_practice_template = model.generate_content(bp_prompt).text.strip()
            st.session_state.current_template = best_practice_template

        with st.spinner("4/4: 수식 추상화 및 팩트 기반 서술 중..."):
            max_b = st.session_state.target_bytes
            min_b = int(max_b * 0.8)
            safe_max_c = int((max_b / 3) * 0.95) 
            min_c = int(min_b / 3)
            
            prompt = f"""
            아래 [데이터]만을 활용하여 학생의 실제 NEIS 교과세특을 작성하세요.

            [데이터]
            - 과목명: {subject}
            - 성취도: {grade_level}
            - 교사의 보고서 역량 평가: {report_eval if report_eval.strip() else "(자동 분석)"}
            - 교사의 인지적/인성 평가: {general_eval if general_eval.strip() else "(미기재)"}
            - 학생 다중 보고서 텍스트: {student_report_text[:2000]}

            [🔥 V34 최우선 엄수 규칙: 문법 교정 및 멸균 🔥]
            1. 간결한 호흡: 한 문장이 너무 길어지지 않도록, 팩트 단위로 문장을 적절히 끊어서 서술하세요.
            2. 자연스러운 시작: 절대 '과목에서' 같은 말로 시작하지 마세요.
            3. 수식 절대 작성 금지 (추상화 요약): 수식이나 공식을 한글 발음으로 절대 적지 마세요. "수학적 원리를 도출함"과 같이 '원리와 목적'만 우회하여 압축하세요.
            4. 분량 및 팩트 보존: 글자 수를 무조건 **최소 {min_c}자 이상, {safe_max_c}자 이하**로 꽉 채우세요.
            5. 마크다운/기호/실명/제목 완벽 금지.
            6. 능동태 및 완벽한 음슴체 (매우 중요): 절대 '~습니다', '~어요'를 쓰지 마세요. 문장 끝은 반드시 명사형 종결어미(~함, ~임, ~됨 등)로 끝내야 합니다. (예: 탐구하였습니다 -> 탐구함 / 보였습니다 -> 보임)
            """
            response = model.generate_content(prompt)
            st.session_state.current_result = response.text.strip()

# ==========================================
# 6. 결과 출력 및 파이썬 스마트 컷오프
# ==========================================
if st.session_state.current_result:
    res_text = st.session_state.current_result
    
    # 1. 마크다운 기호 및 줄바꿈 물리적 파괴
    res_text = res_text.replace("**", "").replace("*", "").replace("#", "")
    res_text = re.sub(r'\n+', ' ', res_text).strip()

    # 2. 제목 및 태그 찌꺼기 절단
    prefixes_to_remove = [
        f"[{subject}]", f"{subject}", "세특 우수 사례:", "가상 세특:", "최종 세특:", 
        "과목명:", "과목에서 ", "본 과목에서 ", "이 과목에서 ", "제목:", "내용:", "세특:", "교과세특:"
    ]
    for _ in range(3):
        for prefix in prefixes_to_remove:
            if res_text.startswith(prefix):
                res_text = res_text[len(prefix):].strip()

    # 💡 3. 존댓말 및 기괴한 어미 강제 교정 (정규식 및 치환)
    # AI가 '습니다'를 썼을 경우 무조건 음슴체로 변경
    res_text = re.sub(r'([가-힣]+)하였습니다\.', r'\1함.', res_text)
    res_text = re.sub(r'([가-힣]+)했습니다\.', r'\1함.', res_text)
    res_text = re.sub(r'([가-힣]+)보였습니다\.', r'\1보임.', res_text)
    res_text = re.sub(r'([가-힣]+)되었습니다\.', r'\1됨.', res_text)
    res_text = re.sub(r'([가-힣]+)있습니다\.', r'\1있음.', res_text)
    res_text = re.sub(r'([가-힣]+)습니다\.', r'\1음.', res_text)

    # 금지어 및 기괴한 어미 치환
    forbidden_replacements = {
        "이 학생은 ": "", "본 학생은 ": "", "학생은 ": "", "자신은 ": "",
        "교과세특": "기록", "세특": "기록", "생기부": "기록", "학교생활기록부": "기록",
        "체득함": "적용함", "이해함": "설명함", "깨달음": "분석함",
        "모습을함": "모습을 보임", "모습을 함": "모습을 보임", 
        "태도를함": "태도를 지님", "태도를 함": "태도를 지님",
        "자신감함": "자신감을 보임", "자신감을함": "자신감을 보임", "자신감임": "자신감을 보임",
        "나섰습니다.": "나섬.", "임했습니다.": "임함."
    }
    for bad_word, good_word in forbidden_replacements.items():
        res_text = res_text.replace(bad_word, good_word)

    # 💡 4. 진정한 문장 단위 스마트 컷오프 (바이트 초과 방지)
    max_target = st.session_state.target_bytes
    if get_byte_length(res_text) > max_target:
        # 마침표(.)를 기준으로 문장 분리
        sentences = [s.strip() + "." for s in res_text.split('.') if s.strip()]
        new_text = ""
        for sentence in sentences:
            # 새로운 문장을 더했을 때 타겟 바이트를 초과하면 중단 (그 문장은 버림)
            candidate = new_text + (" " if new_text else "") + sentence
            if get_byte_length(candidate) <= max_target:
                new_text = candidate
            else:
                break
        
        # 만약 첫 문장조차 너무 길어서 new_text가 비어있다면, 어쩔 수 없이 예전처럼 자름
        if not new_text:
            new_text = sentences[0]
            while get_byte_length(new_text) > (max_target - 5):
                new_text = new_text[:-1]
            new_text += "함."
            
        res_text = new_text

    st.session_state.current_result = res_text

    st.divider()
    st.subheader("🎯 생성된 맞춤형 세특 (문장 단위 절삭 및 존댓말 교정 완료)")
    
    byte_len = get_byte_length(res_text)
    min_target = int(max_target * 0.8)
    
    if byte_len < min_target:
        st.warning(f"⚠️ 분량 미달: {byte_len} Bytes (목표: 최소 {min_target} Bytes). 팩트를 더 추가해 주세요.")
    else: 
        st.success(f"✅ 완벽 분량 및 문장 보호 완료: {byte_len} Bytes (목표 제한: 최대 {max_target} Bytes 이내)")
    
    final_text = st.text_area("결과 확인/수정", value=res_text, height=250)

    with st.expander("🔍 AI가 설계한 뼈대 훔쳐보기 (참고용)"):
        st.info(st.session_state.current_template)

    report_eval_record = report_eval if report_eval.strip() else "(자동 분석)"
    general_eval_record = general_eval if general_eval.strip() else "(미기재)"
    combined_eval = f"[탐구 역량] {report_eval_record}\n[인지/인성] {general_eval_record}"
    
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        pd.DataFrame([{
            "날짜": datetime.now().strftime('%Y-%m-%d %H:%M'), 
            "과목": subject, 
            "등급": grade_level, 
            "종합평가내용": combined_eval, 
            "생성세특": final_text
        }]).to_excel(writer, index=False)
        
    st.download_button(
        label="📂 작성된 세특 엑셀로 다운로드 (개인 PC 보관)",
        data=output.getvalue(),
        file_name=f"{subject}_세특기록_{datetime.now().strftime('%m%d_%H%M')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True
    )
