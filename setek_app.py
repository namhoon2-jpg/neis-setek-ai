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
st.title("📝 NEIS 세특 AI 어시스턴트 (V41: 비중 조절 및 교육과정 연계)")

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
        "📄 교사의 활동/탐구 역량 평가", 
        placeholder="특별히 강조하고 싶은 [교사 평가]가 있다면 적어주세요.\n(비워두실 경우 AI가 보고서를 분석하여 탐구 역량을 스스로 판단하여 평가합니다.)", 
        height=180
    )

with col2:
    general_eval = st.text_area(
        "🧑‍🏫 교사의 인지적/인성 평가", 
        placeholder="학생의 인지적 특성과 인성적 측면에 대한 종합 평가를 적어주세요. 마지막 결론으로 융합됩니다.", 
        height=180
    )

# 💡 V41 핵심 1: 다중 보고서 비중(%) 컨트롤러 UI 구현
st.divider()
st.subheader("📁 보고서 업로드 및 비중 설정")
pdf_files = st.file_uploader("학생 보고서 (PDF) - 최대 3개 선택 가능", type=["pdf"], accept_multiple_files=True)

report_weights = []
if pdf_files:
    if len(pdf_files) > 3:
        st.warning("⚠️ 보고서는 최대 3개까지만 반영됩니다. 처음 3개의 파일만 사용됩니다.")
        pdf_files = pdf_files[:3]
    
    if len(pdf_files) == 1:
        st.info(f"✅ [{pdf_files[0].name}] 100% 비중으로 반영됩니다.")
        report_weights = [100]
    
    elif len(pdf_files) == 2:
        col_w1, col_w2 = st.columns(2)
        with col_w1:
            w1 = st.slider(f"1️⃣ [{pdf_files[0].name}] 반영 비중 (%)", min_value=10, max_value=90, value=50, step=5)
        with col_w2:
            w2 = 100 - w1
            st.info(f"2️⃣ [{pdf_files[1].name}] 반영 비중: {w2}%")
        report_weights = [w1, w2]
        
    elif len(pdf_files) == 3:
        col_w1, col_w2, col_w3 = st.columns(3)
        with col_w1:
            w1 = st.slider(f"1️⃣ [{pdf_files[0].name}] 비중 (%)", min_value=10, max_value=80, value=35, step=5)
        with col_w2:
            w2_max = 100 - w1 - 10
            w2 = st.slider(f"2️⃣ [{pdf_files[1].name}] 비중 (%)", min_value=10, max_value=w2_max, value=min(35, w2_max), step=5)
        with col_w3:
            w3 = 100 - w1 - w2
            st.info(f"3️⃣ [{pdf_files[2].name}] 비중: {w3}%")
        report_weights = [w1, w2, w3]

if st.session_state.authenticated and not st.session_state.db_texts and GSHEET_CSV_URL:
    sync_with_gsheet()

# ==========================================
# 5. 생성 엔진
# ==========================================
if st.button("🚀 세특 초안 생성하기", type="primary", use_container_width=True):
    if not subject:
        st.warning("👈 과목명을 입력해주세요.")
    else:
        # 💡 V41 핵심 2: 2015 개정 교육과정 성취기준 자동 탐색
        with st.spinner("0/4: 2015 개정 교육과정 성취기준 탐색 중..."):
            edu_prompt = f"고등학교 '{subject}' 과목의 2015 개정 교육과정 핵심 성취기준과 학습 목표를 3문장 이내로 요약해줘. 세특 작성 가이드라인으로 쓸거야."
            try:
                edu_standard = model.generate_content(edu_prompt).text.strip()
            except Exception:
                edu_standard = f"'{subject}' 과목의 일반적인 교육과정 성취기준에 부합하도록 작성할 것."
                
        with st.spinner("1/4: 학생 데이터 및 비중 분석 중..."):
            student_report_text = ""
            if pdf_files:
                for idx, file in enumerate(pdf_files):
                    try:
                        weight = report_weights[idx]
                        with pdfplumber.open(file) as pdf:
                            report_content = ""
                            for pg in pdf.pages:
                                text = pg.extract_text()
                                if text: report_content += text + "\n"
                            student_report_text += f"\n--- [보고서 {idx+1} (목표 반영 비중: {weight}%)] ---\n{report_content}"
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
            [동기-과정-결과-평가 흐름] 1.활동 동기 -> 2.탐구 과정 -> 3.결과 도출 -> 4.교사 평가(없으면 AI가 직접 평가)의 순서로 인과관계가 자연스럽게 이어지도록 서술하세요. 과정 중간에 "이는 ~ 핵심 과정임" 같은 메타 평가는 금지합니다.
            [공통 가이드라인] {guidelines}
            위 규칙을 지켜 '{subject}' 과목의 세특 뼈대를 단일 문단으로 가상으로 작성하세요.
            """
            best_practice_template = model.generate_content(bp_prompt).text.strip()
            st.session_state.current_template = best_practice_template

        with st.spinner("4/4: 교육과정 연계 및 비중 맞춤형 서술 중..."):
            max_b = st.session_state.target_bytes
            min_b = int(max_b * 0.8)
            safe_max_c = int((max_b / 3) * 0.95) 
            min_c = int(min_b / 3)
            
            # 💡 V41 핵심 3: 교육과정 부합성 및 비중 분배 프롬프트 추가
            prompt = f"""
            아래 [데이터]만을 활용하여 학생의 실제 NEIS 교과세특을 작성하세요.

            [데이터]
            - 과목명: {subject}
            - 성취도: {grade_level}
            - 2015 개정 교육과정 성취기준: {edu_standard}
            - 교사의 보고서 역량 평가: {report_eval if report_eval.strip() else "(없음 - AI 임의 창작 금지)"}
            - 교사의 인지적/인성 평가: {general_eval if general_eval.strip() else "(없음 - AI 임의 창작 금지)"}
            - 학생 다중 보고서 텍스트: {student_report_text[:2000]}

            [🔥 V41 최우선 엄수 규칙: 교육과정 연계, 비중 배분 및 서사 최적화 🔥]
            1. 교육과정 부합성 (매우 중요): 서술 시 [2015 개정 교육과정 성취기준]에 제시된 핵심어와 목표를 자연스럽게 문맥에 녹여내어, 학생의 탐구 활동이 철저히 정규 교육과정에 부합하는 심화 활동임을 증명하세요.
            2. 다중 보고서 비중 배분: 여러 개의 보고서가 입력된 경우, 각 보고서 제목에 표시된 [목표 반영 비중(%)]에 비례하여 전체 글의 분량을 배분하여 서술하세요.
            3. 동기-과정-결과-평가의 완벽한 흐름: [활동 동기] ➡️ [구체적 탐구 과정] ➡️ [결과 도출] ➡️ [최종 평가] 순서로 자연스러운 꼬리물기 흐름을 만드세요. 마지막 [최종 평가]에는 교사의 입력이 있으면 그것을 쓰고, 없다면 AI가 보고서를 분석해 학생의 역량을 직접 평가하여 자연스럽게 글을 닫아주세요.
            4. 과정 중 의미 부여(메타 평가) 금지: 탐구 과정을 서술하는 중간에 "이는 ~하는 핵심 과정임" 처럼 스스로 포장하는 멘트를 절대 넣지 마세요.
            5. 실명 노출 절대 금지 (시스템 오류 원인): 보고서에 기재된 본명은 단 1글자라도 출력되면 안 됩니다. 주어 자체를 생략하세요.
            6. 영문 알파벳 및 수식 기호 전면 금지: x, y, L1, theta, +, -, =, ^ 등의 수학 기호나 영문 변수를 단 한 글자도 쓰지 마세요. 무조건 순수 한글 명사로만 치환하여 요약하세요.
            7. 학교생활 맞춤 어휘 사용: '동료'라는 단어는 반드시 '급우' 또는 '모둠원'으로 쓰세요.
            8. 분량 및 팩트 보존: 글자 수를 무조건 **최소 {min_c}자 이상, {safe_max_c}자 이하**로 꽉 채우세요.
            9. 능동태 및 완벽한 음슴체: '~습니다', '~어요' 금지. 문장 끝은 명사형 종결어미(~함, ~임, ~됨 등)로 끝내세요.
            """
            response = model.generate_content(prompt)
            st.session_state.current_result = response.text.strip()

# ==========================================
# 6. 결과 출력 및 파이썬 스마트 컷오프 (멸균 유지)
# ==========================================
if st.session_state.current_result:
    res_text = st.session_state.current_result
    
    res_text = re.sub(r'[\$\^_\\]', '', res_text) 
    res_text = res_text.replace("{", "").replace("}", "")

    res_text = res_text.replace("**", "").replace("*", "").replace("#", "")
    res_text = re.sub(r'\n+', ' ', res_text).strip()

    prefixes_to_remove = [
        f"[{subject}]", f"{subject}", "세특 우수 사례:", "가상 세특:", "최종 세특:", 
        "과목명:", "과목에서 ", "본 과목에서 ", "이 과목에서 ", "제목:", "내용:", "세특:", "교과세특:"
    ]
    for _ in range(3):
        for prefix in prefixes_to_remove:
            if res_text.startswith(prefix):
                res_text = res_text[len(prefix):].strip()

    res_text = re.sub(r'([가-힣]+)하였습니다\.', r'\1함.', res_text)
    res_text = re.sub(r'([가-힣]+)했습니다\.', r'\1함.', res_text)
    res_text = re.sub(r'([가-힣]+)보였습니다\.', r'\1보임.', res_text)
    res_text = re.sub(r'([가-힣]+)되었습니다\.', r'\1됨.', res_text)
    res_text = re.sub(r'([가-힣]+)있습니다\.', r'\1있음.', res_text)
    res_text = re.sub(r'([가-힣]+)습니다\.', r'\1음.', res_text)

    forbidden_replacements = {
        "이 학생은 ": "", "본 학생은 ": "", "학생은 ": "", "자신은 ": "",
        "교과세특": "기록", "세특": "기록", "생기부": "기록", "학교생활기록부": "기록",
        "체득함": "적용함", "이해함": "설명함", "깨달음": "분석함",
        "모습을함": "모습을 보임", "모습을 함": "모습을 보임", 
        "태도를함": "태도를 지님", "태도를 함": "태도를 지님",
        "자신감함": "자신감을 보임", "자신감을함": "자신감을 보임", "자신감임": "자신감을 보임",
        "나섰습니다.": "나섬.", "임했습니다.": "임함.",
        "동료": "급우", "동료들": "급우들",
        "경험임.": "역량을 기름.", "경험임": "역량을 기름"
    }
    for bad_word, good_word in forbidden_replacements.items():
        res_text = res_text.replace(bad_word, good_word)

    max_target = st.session_state.target_bytes
    if get_byte_length(res_text) > max_target:
        sentences = [s.strip() + "." for s in res_text.split('.') if s.strip()]
        new_text = ""
        for sentence in sentences:
            candidate = new_text + (" " if new_text else "") + sentence
            if get_byte_length(candidate) <= max_target:
                new_text = candidate
            else:
                break
        
        if not new_text:
            new_text = sentences[0]
            while get_byte_length(new_text) > (max_target - 5):
                new_text = new_text[:-1]
            new_text += "함."
            
        res_text = new_text

    st.session_state.current_result = res_text

    st.divider()
    st.subheader("🎯 생성된 맞춤형 세특 (비중 조절 및 교육과정 부합성 적용)")
    
    byte_len = get_byte_length(res_text)
    min_target = int(max_target * 0.8)
    
    if byte_len < min_target:
        st.warning(f"⚠️ 분량 미달: {byte_len} Bytes (목표: 최소 {min_target} Bytes). 팩트를 더 추가해 주세요.")
    else: 
        st.success(f"✅ 완벽 분량 및 문장 보호 완료: {byte_len} Bytes (목표 제한: 최대 {max_target} Bytes 이내)")
    
    final_text = st.text_area("결과 확인/수정", value=res_text, height=250)

    with st.expander("🔍 AI가 설계한 뼈대 및 교육과정 매핑 훔쳐보기 (참고용)"):
        st.info(st.session_state.current_template)

    report_eval_record = report_eval if report_eval.strip() else "(AI 자동 평가)"
    general_eval_record = general_eval if general_eval.strip() else "(AI 자동 평가)"
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
