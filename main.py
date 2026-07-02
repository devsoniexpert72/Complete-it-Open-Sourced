import os
import json
import secrets
import requests
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from supabase import create_client

# ==========================================
# 1. CONFIGURATION & SETUP
# ==========================================
CREDENTIALS_FILE = "credentials.json"
SUPABASE_URL = os.getenv("SUPABASE_URL", "YOUR_SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "YOUR_SUPABASE_KEY")
REDIRECT_URI = "https://complete-it.onrender.com"

app = FastAPI(title="Complete It")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# ==========================================
# 2. AUTHENTICATION
# ==========================================
class AuthRequest(BaseModel):
    code: str

def get_google_cfg():
    try:
        with open(CREDENTIALS_FILE, "r") as f:
            data = json.load(f)
        cfg = data.get("web") or data.get("installed")
        return cfg["client_id"], cfg["client_secret"], cfg.get("auth_uri", "https://accounts.google.com/o/oauth2/auth")
    except FileNotFoundError:
        return "MISSING", "MISSING", "https://accounts.google.com/o/oauth2/auth"

@app.get("/api/auth/url")
def get_auth_url():
    client_id, _, auth_uri = get_google_cfg()
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "scope": "openid email profile",
        "access_type": "offline",
        "prompt": "select_account",
    }
    url = requests.Request("GET", auth_uri, params=params).prepare().url
    return {"url": url}

@app.post("/api/auth/callback")
def callback(req: AuthRequest):
    client_id, client_secret, _ = get_google_cfg()
    resp = requests.post("https://oauth2.googleapis.com/token", data={
        "code": req.code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": REDIRECT_URI,
        "grant_type": "authorization_code",
    })
    if resp.status_code != 200:
        raise HTTPException(status_code=400, detail="Google Auth Failed")
    token_data = resp.json()
    user_info = requests.get("https://openidconnect.googleapis.com/v1/userinfo", headers={"Authorization": f"Bearer {token_data['access_token']}"}).json()
    
    user_payload = {
        "id": user_info["sub"],
        "email": user_info.get("email"),
        "name": user_info.get("name"),
        "picture": user_info.get("picture")
    }
    supabase.table("users").upsert(user_payload).execute()
    
    session_token = secrets.token_hex(32)
    supabase.table("sessions").insert({"token": session_token, "user_id": user_info["sub"]}).execute()
    
    return {"token": session_token, "user": user_payload}

@app.get("/api/me")
def get_me(token: str):
    session_query = supabase.table("sessions").select("user_id").eq("token", token).execute()
    if not session_query.data:
        raise HTTPException(status_code=401, detail="Session expired")
    user_id = session_query.data[0]['user_id']
    user_query = supabase.table("users").select("*").eq("id", user_id).execute()
    return user_query.data[0]

@app.post("/api/auth/logout")
def logout(token: str):
    supabase.table("sessions").delete().eq("token", token).execute()
    return {"status": "ok"}

# ==========================================
# 3. DATA ENDPOINTS
# ==========================================
@app.get("/api/library/textbooks")
def get_textbooks():
    covers = supabase.table("textbook_thumbnails").select("*").execute().data
    chapters = supabase.table("textbooks").select("*").order("sort_order").execute().data
    return {"covers": covers, "chapters": chapters}

@app.get("/api/library/notebooks")
def get_notebooks():
    try:
        chapters = supabase.table("notebooks").select("*").order("sort_order").execute().data
        return {"chapters": chapters}
    except Exception:
        return {"chapters": []}

@app.get("/api/homework")
def get_homework(limit: int = 1):
    res = supabase.table("homework_logs").select("*").order("fetch_date", desc=True).limit(limit).execute()
    return res.data

@app.get("/api/materials")
def get_materials():
    res = supabase.table("classroom_materials").select("*").order("received_at", desc=True).execute()
    return res.data

@app.get("/api/resources")
def get_resources():
    try:
        res = supabase.table("resources").select("*").order("created_at", desc=True).execute()
        return res.data
    except Exception:
        return []

@app.get("/api/announcements")
def get_announcements():
    res = supabase.table("announcements").select("*").eq("is_active", True).order("created_at", desc=True).execute()
    return res.data

@app.get("/api/circulars")
def get_circulars(page: int = 1, limit: int = 30, show_fees: bool = False):
    offset = (page - 1) * limit
    query = supabase.table("circulars").select("*").order("fetch_date", desc=True)
    if not show_fees:
        query = query.or_("fee_related.eq.false,fee_related.is.null")
    res = query.range(offset, offset + limit - 1).execute()
    return res.data

# ==========================================
# 4. FRONTEND UI
# ==========================================
HTML_CONTENT = """
<!DOCTYPE html>
<html lang="en" class="scroll-smooth">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Complete It</title>
    <script>
        (function () {
            const getCookie = (name) => document.cookie.split('; ').find((row) => row.startsWith(name + '='))?.split('=')[1];
            const storedTheme = sessionStorage.getItem('pref_theme') || getCookie('pref_theme');
            const storedAccent = sessionStorage.getItem('pref_accent') || getCookie('pref_accent') || '#14b8a6';
            const useDark = storedTheme ? storedTheme === 'dark' : window.matchMedia('(prefers-color-scheme: dark)').matches;
            document.documentElement.classList.toggle('dark', useDark);
            document.documentElement.style.setProperty('--accent', decodeURIComponent(storedAccent));
        })();
    </script>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
    <script>
        tailwind.config = {
            darkMode: 'class',
            theme: {
                extend: {
                    fontFamily: { sans: ['Plus Jakarta Sans', 'sans-serif'] },
                    colors: { brand: { 50: '#f0fdfa', 100: '#ccfbf1', 500: 'var(--accent)', 600: 'color-mix(in srgb, var(--accent) 80%, black)', 900: 'color-mix(in srgb, var(--accent) 40%, black)' } }
                }
            }
        }
    </script>
    <style>
        :root { --accent: #14b8a6; }
        body { background: #f8fafc; color: #0f172a; transition: background-color 300ms ease, color 300ms ease; overflow-x: hidden; }
        .dark body { background: #020617; color: #f1f5f9; }
        
        .glass { background: rgba(255, 255, 255, 0.88); backdrop-filter: blur(16px); -webkit-backdrop-filter: blur(16px); border: 1px solid rgba(148, 163, 184, 0.25); box-shadow: 0 8px 30px rgba(15, 23, 42, 0.08); }
        .dark .glass { background: rgba(15, 23, 42, 0.85); border-color: rgba(71, 85, 105, 0.45); box-shadow: 0 10px 35px rgba(0, 0, 0, 0.45); }

        .accent-text { color: var(--accent) !important; }
        .accent-bg { background: var(--accent) !important; }
        .swatch.active { border-color: white; box-shadow: 0 0 0 2px var(--accent); transform: translateY(-2px) scale(1.1); }

        .ambient-bg { position: fixed; inset: 0; z-index: -1; pointer-events: none; overflow: hidden; background: radial-gradient(70rem 35rem at 8% -10%, rgba(15, 23, 42, 0.04), transparent 60%), radial-gradient(55rem 30rem at 92% -12%, color-mix(in srgb, var(--accent) 10%, transparent), transparent 62%), linear-gradient(180deg, rgba(255,255,255,0), #f8fafc); }
        .dark .ambient-bg { background: radial-gradient(70rem 35rem at 8% -10%, rgba(30, 41, 59, 0.4), transparent 60%), radial-gradient(55rem 30rem at 92% -12%, color-mix(in srgb, var(--accent) 15%, transparent), transparent 62%), linear-gradient(180deg, rgba(2,6,23,0), #020617); }

        .split-text .char { display: inline-block; opacity: 0; transform: translateY(18px) scale(0.98); animation: charIn 850ms cubic-bezier(0.22, 1, 0.36, 1) forwards; animation-delay: calc(var(--i) * 38ms); }
        @keyframes charIn { to { opacity: 1; transform: translateY(0) scale(1); } }

        .pro-card { position: relative; isolation: isolate; overflow: hidden; transition: transform 300ms cubic-bezier(0.34, 1.56, 0.64, 1), box-shadow 300ms ease; }
        .pro-card::before { content: ""; position: absolute; inset: -1px; border-radius: inherit; background: radial-gradient(250px circle at var(--mx, 50%) var(--my, 50%), color-mix(in srgb, var(--accent) 90%, white 10%) 0%, transparent 60%); opacity: var(--border-o, 0); transition: opacity 320ms ease; z-index: -1; }
        .pro-card::after { content: ""; position: absolute; inset: 1px; border-radius: inherit; background: inherit; z-index: -1; transition: background 300ms ease; }
        .pro-card:hover { --border-o: 1; transform: translateY(-2px); }

        .book-scene { perspective: 1200px; }
        .physical-book { transform-style: preserve-3d; transition: transform 0.6s cubic-bezier(0.34, 1.56, 0.64, 1), box-shadow 0.5s ease; transform-origin: left center; border-radius: 2px 12px 12px 2px; box-shadow: inset 4px 0 10px rgba(0,0,0,0.1), 5px 15px 25px rgba(0,0,0,0.15); }
        .dark .physical-book { box-shadow: inset 4px 0 10px rgba(255,255,255,0.05), 5px 15px 30px rgba(0,0,0,0.6); }
        .physical-book::before { content: ''; position: absolute; top: 0; bottom: 0; left: 0; width: 16px; background: linear-gradient(to right, rgba(255,255,255,0.3), rgba(0,0,0,0.1) 40%, rgba(255,255,255,0.1) 100%); border-radius: 2px 0 0 2px; z-index: 20; }
        .book-scene:hover .physical-book { transform: rotateY(-9deg) scale(1.02); cursor: pointer; }
        
        /* Restored Notebook Gradient */
        .notebook-cover { background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%); box-shadow: inset 0 0 40px rgba(0,0,0,0.2); }
        .dark .notebook-cover { background: linear-gradient(135deg, #312e81 0%, #4c1d95 100%); }

        .tab-content { display: none; opacity: 0; }
        .tab-content.active { display: block; animation: fadeUp 0.4s cubic-bezier(0.16, 1, 0.3, 1) forwards; }
        @keyframes fadeUp { from { opacity: 0; transform: translateY(15px); } to { opacity: 1; transform: translateY(0); } }
        
        .dropdown { display: none; transform-origin: top right; }
        .dropdown.active { display: block; animation: scaleIn 0.2s cubic-bezier(0.16, 1, 0.3, 1) forwards; }
        @keyframes scaleIn { from { opacity: 0; transform: scale(0.95); } to { opacity: 1; transform: scale(1); } }
        details > summary { list-style: none; }
        details > summary::-webkit-details-marker { display: none; }

        #reader-view { position: fixed; inset: 0; z-index: 100; transform: translateY(100%); transition: transform 0.36s cubic-bezier(0.22, 1, 0.36, 1); background: inherit; overflow-y: auto; }
        #reader-view.active { transform: translateY(0); }

        ::-webkit-scrollbar { width: 8px; height: 8px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: rgba(148, 163, 184, 0.3); border-radius: 10px; }
        ::-webkit-scrollbar-thumb:hover { background: rgba(148, 163, 184, 0.5); }

        @media (max-width: 768px) {
            .ambient-bg { background-size: cover; }
            .pro-card:hover { transform: none; }
            .split-text .char { animation-duration: 520ms; }
        }
        @media (prefers-reduced-motion: reduce) {
            *, *::before, *::after { animation: none !important; transition: none !important; }
        }
    </style>
</head>
<body class="antialiased">
    <div class="ambient-bg"></div>
    
    <div id="login-view" class="fixed inset-0 z-50 flex items-center justify-center bg-slate-50/80 dark:bg-slate-950/80 backdrop-blur-xl hidden overflow-hidden">
        <div class="bg-white/90 dark:bg-slate-900/90 p-12 rounded-[2.5rem] w-full max-w-md text-center shadow-[0_20px_60px_-15px_rgba(0,0,0,0.1)] dark:shadow-[0_20px_60px_-15px_rgba(0,0,0,0.6)] border border-white/50 dark:border-slate-700/50 relative overflow-hidden pro-card backdrop-blur-md">
            <div class="absolute top-0 left-0 w-full h-1.5 bg-gradient-to-r from-brand-500 to-blue-500"></div>
            <img src="https://lcdqoyvjytdazozmwmiu.supabase.co/storage/v1/object/public/Brand-Assets/icon_logo.svg" class="w-24 h-24 mx-auto mb-6 drop-shadow-2xl transform transition-transform hover:scale-105 duration-500" alt="Logo">
            <h1 class="text-3xl font-black mb-2 tracking-tight text-slate-900 dark:text-white split-text">Complete It</h1>
            <p class="text-slate-500 dark:text-slate-400 mb-10 font-medium">Your Ultimate Academic Workspace</p>
            <button onclick="loginWithGoogle()" class="w-full py-4 px-6 bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-2xl flex items-center justify-center gap-3 hover:bg-slate-50 dark:hover:bg-slate-700 hover:shadow-lg hover:-translate-y-1 transition-all duration-300 font-bold text-slate-700 dark:text-slate-200">
                <svg class="w-5 h-5" viewBox="0 0 24 24"><path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/><path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/><path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/><path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/></svg>
                Sign in with Google
            </button>
        </div>
    </div>

    <div id="app-view" class="min-h-screen hidden">
        <header class="fixed top-0 w-full z-40 glass border-b border-slate-200/50 dark:border-slate-800/50">
            <div class="max-w-7xl mx-auto px-6 h-20 flex items-center justify-between">
                <div class="flex items-center gap-3">
                    <img src="https://lcdqoyvjytdazozmwmiu.supabase.co/storage/v1/object/public/Brand-Assets/icon_logo.svg" class="w-10 h-10 drop-shadow-md" alt="Logo">
                    <h1 class="text-xl font-black tracking-tight hidden sm:block text-slate-900 dark:text-white">Complete It</h1>
                </div>
                
                <nav class="relative hidden md:flex items-center gap-1 bg-slate-200/50 dark:bg-slate-800/50 p-1.5 rounded-2xl border border-slate-200 dark:border-slate-700/50">
                    <div id="nav-indicator" class="absolute h-9 bg-white dark:bg-slate-700 rounded-xl shadow-sm transition-all duration-300 cubic-bezier(0.4, 0, 0.2, 1) z-0" style="width: 0; left: 0; opacity: 0;"></div>
                    <button data-tab="textbooks" onclick="switchTab('textbooks', this)" class="tab-btn relative z-10 px-5 py-2 rounded-xl text-sm font-bold text-slate-500 hover:text-slate-900 dark:hover:text-white transition-colors">Textbooks</button>
                    <button data-tab="notebooks" onclick="switchTab('notebooks', this)" class="tab-btn relative z-10 px-5 py-2 rounded-xl text-sm font-bold text-slate-500 hover:text-slate-900 dark:hover:text-white transition-colors">Notebooks</button>
                    <button data-tab="homework" onclick="switchTab('homework', this)" class="tab-btn relative z-10 px-5 py-2 rounded-xl text-sm font-bold text-slate-500 hover:text-slate-900 dark:hover:text-white transition-colors">Homework</button>
                    <button data-tab="materials" onclick="switchTab('materials', this)" class="tab-btn relative z-10 px-5 py-2 rounded-xl text-sm font-bold text-slate-500 hover:text-slate-900 dark:hover:text-white transition-colors">Materials</button>
                    <button data-tab="resources" onclick="switchTab('resources', this)" class="tab-btn relative z-10 px-5 py-2 rounded-xl text-sm font-bold text-slate-500 hover:text-slate-900 dark:hover:text-white transition-colors">Resources</button>
                    <button data-tab="circulars" onclick="switchTab('circulars', this)" class="tab-btn relative z-10 px-5 py-2 rounded-xl text-sm font-bold text-slate-500 hover:text-slate-900 dark:hover:text-white transition-colors">Circulars</button>
                </nav>

                <div class="flex items-center gap-3 relative">
                    <div class="relative">
                        <button onclick="toggleDropdown('alerts-dropdown')" class="p-2.5 rounded-full hover:bg-slate-200 dark:hover:bg-slate-800 transition text-slate-500 hover:text-brand-500 relative">
                            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" /></svg>
                            <span id="alert-badge" class="absolute top-1.5 right-2 w-2 h-2 bg-red-500 rounded-full border-2 border-white dark:border-slate-900 hidden"></span>
                        </button>
                        <div id="alerts-dropdown" class="dropdown absolute top-14 right-0 w-80 bg-white/95 dark:bg-slate-900/95 backdrop-blur-xl border border-slate-200 dark:border-slate-800 rounded-2xl shadow-2xl p-4 z-50 pro-card">
                            <h4 class="font-bold text-sm mb-3 px-2">Announcements</h4>
                            <div id="alerts-feed" class="max-h-80 overflow-y-auto space-y-2 no-scrollbar"></div>
                        </div>
                    </div>
                    <div class="relative">
                        <button onclick="toggleDropdown('profile-dropdown')" class="focus:outline-none ring-2 ring-transparent hover:ring-brand-500 rounded-full transition-all">
                            <img id="nav-avatar" src="" class="w-10 h-10 rounded-full object-cover shadow-sm border border-slate-200 dark:border-slate-700" alt="Profile">
                        </button>
                        <div id="profile-dropdown" class="dropdown absolute top-14 right-0 w-72 bg-white/95 dark:bg-slate-900/95 backdrop-blur-xl border border-slate-200 dark:border-slate-800 rounded-[1.5rem] shadow-2xl p-3 z-50 pro-card">
                            <div class="p-4 flex items-center gap-4 border-b border-slate-100 dark:border-slate-800/50 mb-3">
                                <img id="menu-avatar" src="" class="w-12 h-12 rounded-full object-cover">
                                <div>
                                    <h3 id="menu-name" class="font-bold text-sm text-slate-900 dark:text-white"></h3>
                                    <p id="menu-email" class="text-xs text-slate-500 truncate w-40"></p>
                                </div>
                            </div>
                            <button onclick="goToBookmarks()" class="w-full text-left px-4 py-3 text-sm font-bold text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 rounded-xl transition flex items-center gap-2 mb-1">
                                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 5a2 2 0 012-2h10a2 2 0 012 2v16l-7-3.5L5 21V5z"/></svg>
                                Saved Bookmarks
                            </button>
                            <button onclick="openPreferences()" class="w-full text-left px-4 py-3 text-sm font-bold text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 rounded-xl transition flex items-center gap-2 mb-2">
                                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 6V4m0 16v-2m8-6h-2M6 12H4m12.95 4.95l-1.414-1.414M8.464 8.464 7.05 7.05m9.9 0-1.414 1.414M8.464 15.536 7.05 16.95M12 16a4 4 0 100-8 4 4 0 000 8z"/></svg>
                                Preferences
                            </button>
                            <button onclick="logout()" class="w-full text-left px-4 py-3 text-sm font-bold text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-500/10 rounded-xl transition flex items-center gap-2">
                                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1"/></svg>
                                Sign Out
                            </button>
                        </div>
                    </div>
                </div>
            </div>
            
            <div id="mobile-nav" class="md:hidden flex overflow-x-auto gap-2 px-4 pb-3 no-scrollbar border-b border-slate-200 dark:border-slate-800">
                <button data-tab="textbooks" onclick="switchTab('textbooks', this)" class="tab-btn px-4 py-1.5 rounded-full text-xs font-bold bg-slate-100 dark:bg-slate-800 whitespace-nowrap transition-colors">Textbooks</button>
                <button data-tab="notebooks" onclick="switchTab('notebooks', this)" class="tab-btn px-4 py-1.5 rounded-full text-xs font-bold bg-slate-100 dark:bg-slate-800 whitespace-nowrap transition-colors">Notebooks</button>
                <button data-tab="homework" onclick="switchTab('homework', this)" class="tab-btn px-4 py-1.5 rounded-full text-xs font-bold bg-slate-100 dark:bg-slate-800 whitespace-nowrap transition-colors">Homework</button>
                <button data-tab="materials" onclick="switchTab('materials', this)" class="tab-btn px-4 py-1.5 rounded-full text-xs font-bold bg-slate-100 dark:bg-slate-800 whitespace-nowrap transition-colors">Materials</button>
                <button data-tab="resources" onclick="switchTab('resources', this)" class="tab-btn px-4 py-1.5 rounded-full text-xs font-bold bg-slate-100 dark:bg-slate-800 whitespace-nowrap transition-colors">Resources</button>
                <button data-tab="circulars" onclick="switchTab('circulars', this)" class="tab-btn px-4 py-1.5 rounded-full text-xs font-bold bg-slate-100 dark:bg-slate-800 whitespace-nowrap transition-colors">Circulars</button>
            </div>
        </header>

        <main class="pt-28 sm:pt-32 pb-16 sm:pb-20 max-w-7xl mx-auto px-4 sm:px-6">
            <div class="mb-12">
                <h2 class="text-3xl sm:text-4xl md:text-5xl font-black tracking-tight"><span id="welcome-prefix" class="split-text inline-block">Welcome back,</span> <span id="welcome-name" class="accent-text"></span>.</h2>
                <p class="text-slate-500 dark:text-slate-400 mt-3 text-lg font-medium">Pick up right where you left off.</p>
            </div>

            <div id="tab-textbooks" class="tab-content active">
                <div id="textbooks-grid" class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-x-6 gap-y-12"></div>
            </div>

            <div id="tab-notebooks" class="tab-content">
                <div id="notebooks-grid" class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-x-6 gap-y-12"></div>
            </div>

            <div id="tab-homework" class="tab-content max-w-3xl mx-auto">
                <div class="mb-8 relative">
                    <div class="absolute inset-y-0 left-0 pl-4 flex items-center pointer-events-none">
                        <svg class="w-5 h-5 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/></svg>
                    </div>
                    <input type="text" id="hw-search" oninput="debouncedFilterData('hw-item', 'hw-search')" placeholder="Filter by task, teacher, or date..." class="w-full bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl py-4 pl-12 pr-4 focus:ring-2 focus:ring-brand-500 outline-none shadow-sm transition-shadow font-medium">
                </div>
                <div id="homework-feed"></div>
                <button onclick="fetchHomework(30)" class="mt-4 w-full py-4 bg-slate-100 dark:bg-slate-800/50 text-slate-700 dark:text-slate-300 rounded-2xl font-bold hover:bg-slate-200 dark:hover:bg-slate-700 transition-colors border border-slate-200 dark:border-slate-700 flex items-center justify-center gap-2">
                    Load Full 30-Day Log
                </button>
            </div>

            <div id="tab-materials" class="tab-content">
                <div class="mb-8 max-w-md mx-auto relative">
                    <div class="absolute inset-y-0 left-0 pl-4 flex items-center pointer-events-none">
                        <svg class="w-5 h-5 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/></svg>
                    </div>
                    <input type="text" id="mat-search" oninput="debouncedFilterData('mat-item', 'mat-search')" placeholder="Filter materials..." class="w-full bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-full py-3.5 pl-12 pr-4 focus:ring-2 focus:ring-brand-500 outline-none shadow-sm font-medium">
                </div>
                <div id="materials-grid" class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6"></div>
            </div>

            <div id="tab-resources" class="tab-content">
                <div class="mb-8 max-w-4xl mx-auto flex flex-col sm:flex-row gap-4 items-center">
                    <div class="relative flex-1 w-full">
                        <div class="absolute inset-y-0 left-0 pl-4 flex items-center pointer-events-none">
                            <svg class="w-5 h-5 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/></svg>
                        </div>
                        <input type="text" id="res-search" oninput="debouncedFilterResources()" placeholder="Search resources..." class="w-full bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl py-3.5 pl-12 pr-4 focus:ring-2 focus:ring-brand-500 outline-none shadow-sm transition-shadow font-medium">
                    </div>
                    
                    <div class="relative w-full sm:w-48 z-20">
                        <button onclick="toggleDropdown('res-subject-dropdown')" class="w-full bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl py-3.5 px-4 flex items-center justify-between shadow-sm focus:ring-2 focus:ring-brand-500 font-medium text-slate-700 dark:text-slate-300">
                            <span id="res-subject-label" class="truncate">All Subjects</span>
                            <svg class="w-5 h-5 text-slate-400 shrink-0 ml-2" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/></svg>
                        </button>
                        <div id="res-subject-dropdown" class="dropdown absolute top-full mt-2 right-0 w-full bg-white/95 dark:bg-slate-900/95 backdrop-blur-xl border border-slate-200 dark:border-slate-800 rounded-2xl shadow-xl max-h-60 overflow-y-auto pro-card">
                            <ul id="res-subject-list" class="p-2 space-y-1"></ul>
                        </div>
                    </div>
                    
                    <button id="bookmark-filter-btn" onclick="toggleBookmarkFilter()" class="w-full sm:w-auto px-5 py-3.5 rounded-2xl font-bold transition-all border flex items-center justify-center gap-2 border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 text-slate-500 hover:text-brand-500">
                        <svg class="w-5 h-5" fill="currentColor" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 5a2 2 0 012-2h10a2 2 0 012 2v16l-7-3.5L5 21V5z"/></svg>
                        <span class="sm:hidden">Bookmarks</span>
                    </button>
                </div>
                <div id="resources-grid" class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6"></div>
            </div>

            <div id="tab-circulars" class="tab-content max-w-4xl mx-auto">
                <div class="mb-8 relative">
                    <div class="absolute inset-y-0 left-0 pl-4 flex items-center pointer-events-none">
                        <svg class="w-5 h-5 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/></svg>
                    </div>
                    <input type="text" id="circ-search" oninput="debouncedFilterData('circ-item', 'circ-search')" placeholder="Search circulars by title, date, or content..." class="w-full bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl py-4 pl-12 pr-4 focus:ring-2 focus:ring-brand-500 outline-none shadow-sm transition-shadow font-medium">
                </div>
                <div id="circulars-feed"></div>
                <div class="mt-8 flex flex-col sm:flex-row items-center gap-4 justify-center">
                    <button id="load-more-circulars-btn" onclick="fetchCirculars(true)" class="py-3.5 px-8 bg-slate-100 dark:bg-slate-800/50 text-slate-700 dark:text-slate-300 rounded-full font-bold hover:bg-slate-200 dark:hover:bg-slate-700 transition-colors border border-slate-200 dark:border-slate-700 flex items-center justify-center gap-2">
                        Load More Circulars
                    </button>
                    <button id="toggle-fees-btn" onclick="toggleCircularsFees()" class="py-3 px-6 text-sm font-bold rounded-full transition accent-text hover:underline flex items-center gap-1.5">
                        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>
                        Include Fee-Related Circulars
                    </button>
                </div>
            </div>

        </main>
    </div>

    <div id="reader-view" class="bg-slate-50 dark:bg-slate-950">
        <header class="sticky top-0 w-full z-40 glass border-b border-slate-200/50 dark:border-slate-800/50 px-6 h-20 flex items-center gap-6">
            <button onclick="closeReader()" class="p-2.5 rounded-full bg-slate-200 dark:bg-slate-800 hover:bg-slate-300 dark:hover:bg-slate-700 transition flex items-center justify-center">
                <svg class="w-5 h-5 text-slate-700 dark:text-slate-300" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7" /></svg>
            </button>
            <div>
                <span id="reader-type" class="text-[10px] font-extrabold accent-text uppercase tracking-widest block leading-none">Category</span>
                <h2 id="reader-subject" class="text-2xl font-black text-slate-900 dark:text-white leading-tight">Subject Name</h2>
            </div>
        </header>
        <div class="max-w-7xl mx-auto px-6 py-12">
            <div id="reader-grid" class="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-8"></div>
        </div>
    </div>

    <div id="preferences-modal" class="fixed inset-0 z-[120] hidden items-center justify-center p-4 bg-slate-950/60 backdrop-blur-sm">
        <div class="w-full max-w-lg rounded-3xl glass p-8 pro-card">
            <div class="flex items-center justify-between mb-8">
                <div>
                    <h3 class="text-2xl font-black text-slate-900 dark:text-white split-text">Appearance</h3>
                    <p class="text-sm text-slate-500 dark:text-slate-400">Personalize your workspace.</p>
                </div>
                <button onclick="closePreferences()" class="w-10 h-10 flex items-center justify-center rounded-full bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 dark:hover:bg-slate-700 text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-200 transition-colors">
                    <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" /></svg>
                </button>
            </div>
            <div class="space-y-8">
                <div>
                    <p class="text-xs font-black uppercase tracking-widest text-slate-400 mb-3">Theme Mode</p>
                    <div class="grid grid-cols-2 gap-3">
                        <button onclick="setTheme('light')" id="theme-light-btn" class="py-3 rounded-xl border border-slate-200 dark:border-slate-700 font-bold transition-all">Light</button>
                        <button onclick="setTheme('dark')" id="theme-dark-btn" class="py-3 rounded-xl border border-slate-200 dark:border-slate-700 font-bold transition-all">Dark</button>
                    </div>
                </div>
                <div>
                    <p class="text-xs font-black uppercase tracking-widest text-slate-400 mb-3">Accent Color</p>
                    <div class="flex flex-wrap items-center gap-3">
                        <div id="accent-swatches" class="flex flex-wrap gap-3"></div>
                        <div class="w-[1px] h-8 bg-slate-200 dark:bg-slate-700 mx-2"></div>
                        <label class="relative w-9 h-9 rounded-full border-2 border-slate-300 dark:border-slate-600 overflow-hidden flex items-center justify-center cursor-pointer hover:border-brand-500 transition-colors" title="Custom Color">
                            <input type="color" id="custom-accent" onchange="setAccent(this.value)" class="absolute opacity-0 w-20 h-20 cursor-pointer">
                            <svg class="w-4 h-4 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"/></svg>
                        </label>
                    </div>
                </div>
                <button onclick="resetPreferences()" class="w-full py-3.5 rounded-xl border border-slate-200 dark:border-slate-700 font-bold text-slate-500 hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors mt-4">
                    Reset to Defaults
                </button>
            </div>
        </div>
    </div>

    <script>
        const API_BASE = "";
        let currentToken = localStorage.getItem('token');
        let currentUser = null;
        let globalLibraryData = { textbooks: {}, notebooks: {} };
        const ACCENT_OPTIONS = ['#14b8a6', '#3b82f6', '#8b5cf6', '#f43f5e', '#f59e0b', '#22c55e', '#ec4899'];
        const PREF_KEYS = { theme: 'pref_theme', accent: 'pref_accent' };

        let circulars_current_page = 1;
        let circulars_show_fees = false;
        const CIRCULARS_LIMIT = 30;

        let activeTab = ''; 
        
        // --- Optimizations & Lazy Loading Variables ---
        let globalResources = [];
        let displayedResources = [];
        let resourcesCurrentPage = 1;
        const RESOURCES_PER_PAGE = 12;
        
        let bookmarkedResources = JSON.parse(localStorage.getItem('saved_bookmarks') || '[]').map(String);
        let showOnlyBookmarks = false;
        let currentResourceSubject = "";

        // Debounce Utility
        function debounce(func, wait) {
            let timeout;
            return function(...args) {
                clearTimeout(timeout);
                timeout = setTimeout(() => func.apply(this, args), wait);
            };
        }

        const debouncedFilterData = debounce((className, inputId) => filterData(className, inputId), 300);
        const debouncedFilterResources = debounce(() => { resourcesCurrentPage = 1; filterResources(); }, 300);

        window.onload = async () => {
            hydratePreferencesUI();
            initializeMotionFX();
            setupInfiniteScroll();
            const urlParams = new URLSearchParams(window.location.search);
            const code = urlParams.get('code');
            if (code) {
                window.history.replaceState({}, document.title, "/");
                await handleCallback(code);
            } else if (currentToken) {
                await fetchProfile();
            } else {
                document.getElementById('login-view').classList.remove('hidden');
            }
        };

        // --- Preferences & Theming ---
        function setCookie(name, value) { document.cookie = `${name}=${encodeURIComponent(value)}; path=/; max-age=${60 * 60 * 24 * 365}`; }
        function getCookie(name) { return document.cookie.split('; ').find((row) => row.startsWith(name + '='))?.split('=')[1]; }
        function savePreference(key, value) { sessionStorage.setItem(key, value); setCookie(key, value); }

        function setTheme(mode) {
            document.documentElement.classList.toggle('dark', mode === 'dark');
            savePreference(PREF_KEYS.theme, mode);
            hydratePreferencesUI();
        }

        function setAccent(hex) {
            document.documentElement.style.setProperty('--accent', hex);
            savePreference(PREF_KEYS.accent, hex);
            hydratePreferencesUI();
            const picker = document.getElementById('custom-accent');
            if (picker && !ACCENT_OPTIONS.includes(hex.toLowerCase())) picker.value = hex;
        }

        function resetPreferences() {
            setTheme(window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
            setAccent('#14b8a6');
        }

        function hydratePreferencesUI() {
            const theme = sessionStorage.getItem(PREF_KEYS.theme) || getCookie(PREF_KEYS.theme) || (document.documentElement.classList.contains('dark') ? 'dark' : 'light');
            const accent = decodeURIComponent(sessionStorage.getItem(PREF_KEYS.accent) || getCookie(PREF_KEYS.accent) || '#14b8a6');
            
            document.documentElement.style.setProperty('--accent', accent);
            
            const swatchContainer = document.getElementById('accent-swatches');
            if (swatchContainer) {
                swatchContainer.innerHTML = ACCENT_OPTIONS.map((hex) => `
                    <button onclick="setAccent('${hex}')" class="swatch w-9 h-9 rounded-full border-2 border-transparent transition-transform" style="background:${hex}" title="${hex}" aria-label="Set accent ${hex}"></button>
                `).join('');
                [...swatchContainer.children].forEach((el, idx) => el.classList.toggle('active', ACCENT_OPTIONS[idx] === accent.toLowerCase()));
            }

            document.getElementById('theme-light-btn')?.classList.toggle('accent-bg', theme === 'light');
            document.getElementById('theme-light-btn')?.classList.toggle('text-white', theme === 'light');
            document.getElementById('theme-dark-btn')?.classList.toggle('accent-bg', theme === 'dark');
            document.getElementById('theme-dark-btn')?.classList.toggle('text-white', theme === 'dark');
        }

        function openPreferences() { document.getElementById('preferences-modal').classList.remove('hidden'); document.getElementById('preferences-modal').classList.add('flex'); document.querySelectorAll('.dropdown').forEach(el => el.classList.remove('active')); }
        function closePreferences() { document.getElementById('preferences-modal').classList.add('hidden'); document.getElementById('preferences-modal').classList.remove('flex'); }

        // --- Animations & UI ---
        function splitText(el) {
            if (!el || el.dataset.splitReady) return;
            const text = el.textContent; el.dataset.splitReady = '1';
            el.innerHTML = [...text].map((ch, i) => { if (ch === ' ') return `<span class="char" style="--i:${i}">&nbsp;</span>`; return `<span class="char" style="--i:${i}">${ch}</span>`; }).join('');
        }

        function attachProBorder(card) {
            if (!card || card.dataset.borderReady) return;
            const isTouch = window.matchMedia('(pointer: coarse)').matches || window.innerWidth < 820;
            if (isTouch) { card.style.setProperty('--border-o', '0'); return; }
            card.dataset.borderReady = '1';
            let raf = null;
            const setPos = (e) => {
                const r = card.getBoundingClientRect(); const x = ((e.clientX - r.left) / r.width) * 100; const y = ((e.clientY - r.top) / r.height) * 100;
                card.style.setProperty('--mx', `${Math.max(0, Math.min(100, x))}%`); card.style.setProperty('--my', `${Math.max(0, Math.min(100, y))}%`);
            };
            card.addEventListener('mousemove', (e) => { if (raf) return; raf = requestAnimationFrame(() => { setPos(e); raf = null; }); }, { passive: true });
            card.addEventListener('mouseenter', () => card.style.setProperty('--border-o', '1'));
            card.addEventListener('mouseleave', () => card.style.setProperty('--border-o', '0'));
        }

        function initializeMotionFX() {
            document.querySelectorAll('.split-text').forEach(splitText);
            document.querySelectorAll('.pro-card').forEach(attachProBorder);
        }

        function toggleDropdown(id) { 
            const target = document.getElementById(id);
            const isActive = target.classList.contains('active');
            document.querySelectorAll('.dropdown').forEach(el => el.classList.remove('active')); 
            if (!isActive) target.classList.add('active'); 
        }
        
        document.addEventListener('click', (e) => {
            if (!e.target.closest('.dropdown') && !e.target.closest('button[onclick^="toggleDropdown"]')) { document.querySelectorAll('.dropdown').forEach(el => el.classList.remove('active')); }
            if (e.target.id === 'preferences-modal') closePreferences();
        });

        // --- Tabs Logic ---
        function switchTab(tab, btnElement = null) {
            if (activeTab === tab) return; 
            activeTab = tab;

            if (!btnElement) btnElement = document.querySelector(`button[data-tab="${tab}"]`);
            const indicator = document.getElementById('nav-indicator');
            if (indicator && btnElement && btnElement.parentElement.id !== 'mobile-nav') {
                indicator.style.opacity = '1';
                indicator.style.width = `${btnElement.offsetWidth}px`;
                indicator.style.left = `${btnElement.offsetLeft}px`;
            }

            document.querySelectorAll('.tab-btn').forEach(btn => { 
                btn.classList.remove('bg-white', 'dark:bg-slate-700', 'shadow-sm', 'accent-text'); 
            });
            
            document.querySelectorAll(`button[data-tab="${tab}"]`).forEach(btn => { 
                if (btn.parentElement.classList.contains('md:hidden')) {
                    btn.classList.add('bg-white', 'dark:bg-slate-700', 'shadow-sm', 'accent-text'); 
                } else {
                    btn.classList.add('accent-text');
                }
            });

            document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
            document.getElementById(`tab-${tab}`).classList.add('active');

            if(tab === 'textbooks') fetchLibrary('textbooks');
            if(tab === 'notebooks') fetchLibrary('notebooks');
            if(tab === 'homework') fetchHomework(1);
            if(tab === 'materials') fetchMaterials();
            if(tab === 'resources') { resourcesCurrentPage = 1; fetchResources(); }
            if(tab === 'circulars') fetchCirculars(); 
        }

        // --- Auth ---
        async function loginWithGoogle() { const res = await fetch(`${API_BASE}/api/auth/url`); const data = await res.json(); window.location.href = data.url; }
        async function handleCallback(code) {
            try {
                const res = await fetch(`${API_BASE}/api/auth/callback`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ code }) });
                if (!res.ok) throw new Error();
                const data = await res.json();
                currentToken = data.token; localStorage.setItem('token', currentToken); await fetchProfile();
            } catch (err) { document.getElementById('login-view').classList.remove('hidden'); }
        }
        async function fetchProfile() {
            try {
                const res = await fetch(`${API_BASE}/api/me?token=${currentToken}`); if (!res.ok) throw new Error();
                currentUser = await res.json();
                document.getElementById('nav-avatar').src = currentUser.picture;
                document.getElementById('menu-avatar').src = currentUser.picture;
                document.getElementById('menu-name').innerText = currentUser.name;
                document.getElementById('menu-email').innerText = currentUser.email;
                document.getElementById('welcome-name').innerText = currentUser.name.split(' ')[0];
                document.getElementById('login-view').classList.add('hidden'); document.getElementById('app-view').classList.remove('hidden');
                switchTab('textbooks'); fetchAnnouncements();
            } catch (err) { logout(false); }
        }
        async function logout(callApi = true) { if (callApi && currentToken) await fetch(`${API_BASE}/api/auth/logout?token=${currentToken}`, { method: 'POST' }); localStorage.removeItem('token'); location.reload(); }

        const emptyState = (msg) => `<div class="col-span-full text-center py-20"><div class="inline-flex items-center justify-center w-16 h-16 rounded-full bg-slate-100 dark:bg-slate-800 text-slate-400 mb-4"><svg class="w-8 h-8" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M20 13V6a2 2 0 00-2-2H6a2 2 0 00-2 2v7m16 0v5a2 2 0 01-2 2H6a2 2 0 01-2-2v-5m16 0h-2.586a1 1 0 00-.707.293l-2.414 2.414a1 1 0 01-.707.293h-3.172a1 1 0 01-.707-.293l-2.414-2.414A1 1 0 006.586 13H4"/></svg></div><h3 class="text-lg font-bold text-slate-500">${msg}</h3></div>`;
        function filterData(className, inputId) {
            const term = document.getElementById(inputId).value.toLowerCase();
            document.querySelectorAll(`.${className}`).forEach(el => { el.style.display = el.innerText.toLowerCase().includes(term) ? 'block' : 'none'; });
        }

        // --- Library Logic ---
        async function fetchLibrary(type) {
            const res = await fetch(`/api/library/${type}`); const data = await res.json();
            const grid = document.getElementById(`${type}-grid`);
            if(!data.chapters || !data.chapters.length) { grid.innerHTML = emptyState(`No ${type} available.`); return; }
            
            const grouped = {};
            data.chapters.forEach(ch => { const sub = ch.subject || 'Uncategorized'; if(!grouped[sub]) grouped[sub] = { items: [], cover: null }; grouped[sub].items.push(ch); });
            if(type === 'textbooks' && data.covers) { data.covers.forEach(c => { if(grouped[c.subject]) grouped[c.subject].cover = c.thumbnail_url; }); }
            globalLibraryData[type] = grouped;
            
            const sortedSubjects = Object.entries(grouped).sort(([subA], [subB]) => {
                const isExA = /exemplar|exampler/i.test(subA);
                const isExB = /exemplar|exampler/i.test(subB);
                if (isExA && !isExB) return 1;
                if (!isExA && isExB) return -1;
                return subA.localeCompare(subB);
            });

            let html = '';
            for(const [subject, info] of sortedSubjects) {
                if(type === 'textbooks') {
                    const thumb = info.cover || 'https://via.placeholder.com/400x600/1e293b/ffffff?text=No+Cover';
                    html += ` <div class="book-scene w-full group" onclick="openReader('${type}', '${subject}')"> <div class="physical-book relative aspect-[3/4] bg-slate-200 dark:bg-slate-800"> <img src="${thumb}" class="absolute inset-0 w-full h-full object-cover rounded-[2px_12px_12px_2px] z-10"> </div> <div class="mt-5 text-center px-1"><h3 class="font-extrabold text-sm text-slate-800 dark:text-slate-200 uppercase tracking-widest line-clamp-1">${subject}</h3></div> </div>`;
                } else {
                    html += ` <div class="book-scene w-full group" onclick="openReader('${type}', '${subject}')"> <div class="physical-book relative aspect-[3/4] notebook-cover flex flex-col items-center justify-center p-4 text-center"> <span class="text-white font-black text-2xl uppercase tracking-widest break-words drop-shadow-lg">${subject}</span> <span class="text-indigo-200 text-[10px] font-bold mt-3 tracking-widest uppercase">Notebook</span> </div> <div class="mt-5 text-center px-1"><h3 class="font-extrabold text-sm text-slate-800 dark:text-slate-200 uppercase tracking-widest line-clamp-1">${subject}</h3></div> </div>`;
                }
            }
            grid.innerHTML = html; initializeMotionFX();
        }

        function openReader(type, subject) {
            const data = globalLibraryData[type][subject].items;
            document.getElementById('reader-type').innerText = type === 'textbooks' ? 'Textbook Chapters' : 'Notebook Entries';
            document.getElementById('reader-subject').innerText = subject;
            const grid = document.getElementById('reader-grid');
            grid.innerHTML = data.map((item, index) => {
                const title = item.title || item.chapter_title || `Chapter ${index + 1}`;
                const thumb = item.thumbnail_url || 'https://via.placeholder.com/300x400/1e293b/ffffff?text=Doc';
                // Note: removed pro-card from parent wrapper, added targeted glow effects
                return ` 
                <div class="rounded-3xl p-4 flex flex-col items-center text-center bg-white dark:bg-slate-900/50 border border-slate-200 dark:border-slate-800/80 group"> 
                    <div class="aspect-[3/4] w-full rounded-2xl mb-5 bg-slate-100 dark:bg-slate-800 relative overflow-hidden transition-all duration-300 group-hover:shadow-[0_0_25px_-5px_color-mix(in_srgb,var(--accent)_50%,transparent)] group-hover:ring-2 group-hover:ring-brand-500 cursor-pointer"> 
                        <img src="${thumb}" class="absolute inset-0 w-full h-full object-cover transition-transform duration-500 group-hover:scale-105"> 
                    </div> 
                    <h3 class="font-bold text-slate-900 dark:text-white mb-4 line-clamp-2 leading-snug">${title}</h3> 
                    <a href="${item.pdf_link}" target="_blank" class="mt-auto w-full py-3 accent-bg text-white text-sm font-bold rounded-xl transition-all duration-300 hover:shadow-[0_0_20px_-3px_color-mix(in_srgb,var(--accent)_60%,transparent)] hover:-translate-y-0.5 flex items-center justify-center gap-2"> 
                        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"/></svg> Open PDF 
                    </a> 
                </div>`;
            }).join('');
            document.getElementById('reader-view').classList.add('active'); document.body.style.overflow = 'hidden'; initializeMotionFX();
        }
        function closeReader() { document.getElementById('reader-view').classList.remove('active'); document.body.style.overflow = 'auto'; }

        // --- Homework Logic ---
        async function fetchHomework(limit) {
            const res = await fetch(`${API_BASE}/api/homework?limit=${limit}`); const data = await res.json();
            const feed = document.getElementById('homework-feed');
            const html = data.map((hw, idx) => {
                const classIcon = `<svg class="w-4 h-4 text-brand-500 mt-0.5 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253"/></svg>`;
                const homeIcon = `<svg class="w-4 h-4 text-orange-500 mt-0.5 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"/></svg>`;
                const buildList = (arr, icon) => arr.map(item => ` <div class="flex gap-3 items-start py-3 border-b border-slate-100 dark:border-slate-800/50 last:border-0"> ${icon} <div class="flex-1"> <span class="text-[10px] font-extrabold text-slate-400 uppercase tracking-widest block mb-1">${item.subject}</span> <p class="text-sm font-semibold text-slate-800 dark:text-slate-200">${item.task}</p> </div> </div>`).join('');
                const dateStr = new Date(hw.fetch_date).toLocaleDateString(undefined, {weekday: 'long', month: 'short', day: 'numeric'});
                return ` <details class="hw-item group glass pro-card rounded-[2rem] border border-slate-200 dark:border-slate-800/60 mb-6 overflow-hidden transition-all" ${idx === 0 ? 'open' : ''}> <summary class="p-6 cursor-pointer flex items-center justify-between select-none bg-slate-50/50 dark:bg-slate-900/50 hover:bg-slate-100 dark:hover:bg-slate-800/80 transition-colors"> <div class="flex items-center gap-4"> <div class="w-12 h-12 rounded-2xl bg-brand-500/10 flex items-center justify-center text-brand-500"> <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"/></svg> </div> <div> <h3 class="text-xl font-black text-slate-900 dark:text-white">${dateStr}</h3> </div> </div> <div class="w-10 h-10 rounded-full flex items-center justify-center bg-slate-200 dark:bg-slate-800 text-slate-500 group-open:rotate-180 transition-transform duration-300"> <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" /></svg> </div> </summary> <div class="p-6 border-t border-slate-200 dark:border-slate-800/60"> <div class="mb-6"> <h4 class="text-[10px] font-extrabold text-slate-400 uppercase tracking-widest mb-3 flex items-center gap-2">Classwork Executed</h4> <div class="bg-white dark:bg-slate-900/50 rounded-2xl p-4 shadow-sm border border-slate-100 dark:border-slate-800/50">${buildList(hw.class_work, classIcon)}</div> </div> <div> <h4 class="text-[10px] font-extrabold text-slate-400 uppercase tracking-widest mb-3 flex items-center gap-2">Homework Assigned</h4> <div class="bg-white dark:bg-slate-900/50 rounded-2xl p-4 shadow-sm border border-slate-100 dark:border-slate-800/50">${buildList(hw.homework, homeIcon)}</div> </div> </div> </details>`
            });
            feed.innerHTML = html.join(''); initializeMotionFX();
        }

        // --- Materials Logic ---
        async function fetchMaterials() {
            const res = await fetch(`${API_BASE}/api/materials`); const data = await res.json();
            const grid = document.getElementById('materials-grid');
            if(!data.length) { grid.innerHTML = emptyState("No materials found."); return; }
            grid.innerHTML = data.map(m => ` <a href="${m.link}" target="_blank" class="mat-item pro-card block glass p-6 rounded-3xl border border-slate-200 dark:border-slate-800 hover:border-brand-500 hover:shadow-2xl hover:-translate-y-1 transition-all group"> <div class="w-12 h-12 bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 rounded-2xl flex items-center justify-center mb-5 group-hover:bg-brand-500 group-hover:text-white transition-colors"> <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" /></svg> </div> <h3 class="text-lg font-bold text-slate-900 dark:text-white mb-6 line-clamp-2 leading-snug">${m.title}</h3> <div class="flex items-center justify-between text-xs font-bold text-slate-400 border-t border-slate-100 dark:border-slate-800 pt-4"> <div class="flex items-center gap-1.5"><svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" /></svg>${m.teacher}</div> <div class="flex items-center gap-1.5"><svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>${new Date(m.received_at).toLocaleDateString()}</div> </div> </a> `).join('');
            initializeMotionFX();
        }

        // --- Resources & Bookmarks Logic ---
        function toggleBookmark(e, id) {
            e.preventDefault(); e.stopPropagation();
            const strId = String(id);
            if (bookmarkedResources.includes(strId)) {
                bookmarkedResources = bookmarkedResources.filter(b => b !== strId);
            } else {
                bookmarkedResources.push(strId);
            }
            localStorage.setItem('saved_bookmarks', JSON.stringify(bookmarkedResources));
            // Only re-render the chunk we are looking at to not lose scroll position
            renderResources(displayedResources, false, true); 
        }

        function toggleBookmarkFilter() {
            showOnlyBookmarks = !showOnlyBookmarks;
            const btn = document.getElementById('bookmark-filter-btn');
            if (showOnlyBookmarks) {
                btn.classList.add('bg-brand-500', 'text-white', 'border-brand-500');
                btn.classList.remove('bg-white', 'dark:bg-slate-900', 'text-slate-500');
            } else {
                btn.classList.remove('bg-brand-500', 'text-white', 'border-brand-500');
                btn.classList.add('bg-white', 'dark:bg-slate-900', 'text-slate-500');
            }
            resourcesCurrentPage = 1;
            filterResources();
        }

        function goToBookmarks() {
            document.querySelectorAll('.dropdown').forEach(el => el.classList.remove('active'));
            switchTab('resources');
            if (!showOnlyBookmarks) toggleBookmarkFilter();
        }

        function setResourceSubject(subject) {
            currentResourceSubject = subject;
            document.getElementById('res-subject-label').innerText = subject === '' ? 'All Subjects' : subject;
            document.getElementById('res-subject-dropdown').classList.remove('active');
            resourcesCurrentPage = 1;
            filterResources();
        }

        async function fetchResources() {
            if (!globalResources.length) {
                const res = await fetch(`${API_BASE}/api/resources`);
                globalResources = await res.json() || [];
                
                const subjects = [...new Set(globalResources.map(r => r.subject).filter(Boolean))].sort();
                const list = document.getElementById('res-subject-list');
                list.innerHTML = `
                    <li><button onclick="setResourceSubject('')" class="w-full text-left px-4 py-2 rounded-xl text-sm hover:bg-slate-100 dark:hover:bg-slate-800 transition text-slate-700 dark:text-slate-300">All Subjects</button></li>
                    ${subjects.map(s => `<li><button onclick="setResourceSubject('${s}')" class="w-full text-left px-4 py-2 rounded-xl text-sm hover:bg-slate-100 dark:hover:bg-slate-800 transition text-slate-700 dark:text-slate-300">${s}</button></li>`).join('')}
                `;
            }
            filterResources();
        }

        function filterResources() {
            const term = document.getElementById('res-search').value.toLowerCase();
            
            displayedResources = globalResources.filter(r => {
                const searchMatch = (r.title || '').toLowerCase().includes(term) || 
                                    (r.description || '').toLowerCase().includes(term) || 
                                    (r.tags || []).some(t => t.toLowerCase().includes(term));
                const subjectMatch = currentResourceSubject ? (r.subject === currentResourceSubject) : true;
                const bookmarkMatch = showOnlyBookmarks ? bookmarkedResources.includes(String(r.id)) : true;
                return searchMatch && subjectMatch && bookmarkMatch;
            });
            renderResources(displayedResources, false);
        }

        function renderResources(data, append = false, refreshOnly = false) {
            const grid = document.getElementById('resources-grid');
            
            if(!append && !refreshOnly) {
                grid.innerHTML = '';
                if(!data.length) { 
                    grid.innerHTML = emptyState(showOnlyBookmarks ? "You haven't saved any bookmarks yet." : "No resources found matching criteria."); 
                    return; 
                }
            }

            // Slice data for lazy loading
            const start = refreshOnly ? 0 : (append ? (resourcesCurrentPage - 1) * RESOURCES_PER_PAGE : 0);
            const end = refreshOnly ? (resourcesCurrentPage * RESOURCES_PER_PAGE) : (resourcesCurrentPage * RESOURCES_PER_PAGE);
            const chunk = data.slice(start, end);

            if (!chunk.length && append) return;
            
            const html = chunk.map(r => {
                const dateStr = new Date(r.resource_date || r.created_at).toLocaleDateString(undefined, {month:'short', day:'numeric', year:'numeric'});
                const tagsHtml = (r.tags || []).map(t => `<span class="px-2 py-1 bg-slate-100 dark:bg-slate-800 text-slate-500 dark:text-slate-400 rounded-md text-[9px] font-black uppercase tracking-wider">${t}</span>`).join('');
                const iconHtml = r.icon_url ? `<img src="${r.icon_url}" class="w-5 h-5 rounded-md shrink-0 object-contain" alt="icon">` : `<svg class="w-5 h-5 text-brand-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" /></svg>`;
                const downloadBtn = r.download_url ? `<a href="${r.download_url}" target="_blank" rel="noopener" class="px-3 py-1.5 bg-brand-500/10 text-brand-600 dark:text-brand-400 hover:bg-brand-500 hover:text-white rounded-lg text-xs font-bold transition-colors flex items-center gap-1 shrink-0"><svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"/></svg></a>` : '';
                
                let domainStr = 'External Link';
                if(r.download_url) { try { domainStr = new URL(r.download_url).hostname.replace(/^www\\./, ''); } catch(e) {} }

                const isBookmarked = bookmarkedResources.includes(String(r.id));
                const bookmarkSvg = isBookmarked 
                    ? `<svg class="w-5 h-5 text-brand-500 drop-shadow-sm" fill="currentColor" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 5a2 2 0 012-2h10a2 2 0 012 2v16l-7-3.5L5 21V5z"/></svg>`
                    : `<svg class="w-5 h-5 text-slate-300 dark:text-slate-600 group-hover:text-brand-500 transition-colors" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 5a2 2 0 012-2h10a2 2 0 012 2v16l-7-3.5L5 21V5z"/></svg>`;

                return `
                <div class="res-item pro-card flex flex-col glass p-6 rounded-3xl border border-slate-200 dark:border-slate-800 hover:border-brand-500 hover:shadow-xl hover:-translate-y-1 transition-all group relative">
                    <button onclick="toggleBookmark(event, '${r.id}')" class="absolute top-4 right-4 p-2 rounded-full hover:bg-slate-100 dark:hover:bg-slate-800 z-20 cursor-pointer transition">
                        ${bookmarkSvg}
                    </button>
                    
                    <div class="flex items-start gap-4 mb-5 pr-10">
                        <div class="w-12 h-12 bg-slate-100 dark:bg-slate-800 rounded-2xl flex items-center justify-center shrink-0 overflow-hidden shadow-sm">
                            ${iconHtml}
                        </div>
                        <div class="pt-1">
                            <span class="text-[10px] font-extrabold accent-text uppercase tracking-widest bg-brand-500/10 px-2 py-0.5 rounded-md block mb-1 w-max">${r.subject || 'General'}</span>
                            <a href="${r.download_url}" target="_blank" class="block text-xs font-bold text-slate-500 hover:accent-text transition-colors truncate max-w-[160px]">${domainStr}</a>
                        </div>
                    </div>
                    
                    <h3 class="text-lg font-bold text-slate-900 dark:text-white mb-2 line-clamp-2 leading-snug">
                        <a href="${r.download_url}" target="_blank" class="hover:underline">${r.title}</a>
                    </h3>
                    <p class="text-sm text-slate-500 dark:text-slate-400 mb-5 line-clamp-2 flex-1 font-medium">${r.description || ''}</p>
                    
                    <div class="flex flex-wrap gap-1.5 mb-5">${tagsHtml}</div>
                    
                    <div class="flex items-center justify-between text-xs font-bold text-slate-400 border-t border-slate-100 dark:border-slate-800 pt-4 mt-auto">
                        <div class="flex items-center gap-1.5 truncate">
                            <svg class="w-4 h-4 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"/></svg>
                            ${dateStr}
                        </div>
                        ${downloadBtn}
                    </div>
                </div>`;
            }).join('');

            if(append) grid.innerHTML += html;
            else grid.innerHTML = html;
            
            initializeMotionFX();
        }

        function setupInfiniteScroll() {
            window.addEventListener('scroll', () => {
                if(activeTab === 'resources') {
                    const { scrollTop, scrollHeight, clientHeight } = document.documentElement;
                    // Trigger load slightly before reaching the absolute bottom
                    if(scrollTop + clientHeight >= scrollHeight - 150) {
                        if (resourcesCurrentPage * RESOURCES_PER_PAGE < displayedResources.length) {
                            resourcesCurrentPage++;
                            renderResources(displayedResources, true);
                        }
                    }
                }
            });
        }

        // --- Circulars Logic ---
        async function fetchCirculars(loadMore = false) {
            if (!loadMore) {
                circulars_current_page = 1;
                document.getElementById('circulars-feed').innerHTML = '';
                document.getElementById('load-more-circulars-btn').style.display = 'block';
            } else {
                circulars_current_page++;
            }

            try {
                const res = await fetch(`/api/circulars?page=${circulars_current_page}&limit=${CIRCULARS_LIMIT}&show_fees=${circulars_show_fees}`);
                const data = await res.json();
                const feed = document.getElementById('circulars-feed');

                if (!data.length) {
                    if (!loadMore) feed.innerHTML = emptyState(`No circulars found${circulars_show_fees ? '' : ' (excluding fee-related)'}.`);
                    document.getElementById('load-more-circulars-btn').style.display = 'none';
                    return;
                }

                const html = data.map(circ => {
                    const dateStr = circ.fetch_date ? new Date(circ.fetch_date).toLocaleDateString(undefined, {weekday: 'short', year: 'numeric', month: 'short', day: 'numeric'}) : 'No date';
                    const feeBadge = circ.fee_related ? `<span class="px-2 py-0.5 text-[9px] font-black uppercase tracking-widest text-red-600 dark:text-red-400 bg-red-100 dark:bg-red-950 rounded-md shrink-0">Fee Related</span>` : '';
                    const contentHtml = circ.content ? `<div class="mt-4 text-sm text-slate-700 dark:text-slate-300 leading-relaxed">${circ.content}</div>` : '';

                    return `
                        <details class="circ-item group glass pro-card rounded-[2rem] border border-slate-200 dark:border-slate-800/60 mb-5 overflow-hidden transition-all">
                            <summary class="p-5 cursor-pointer flex items-center justify-between select-none hover:bg-slate-100 dark:hover:bg-slate-800/80 transition-colors">
                                <div>
                                    <div class="flex items-center gap-2.5 mb-1.5">${feeBadge}<h3 class="text-base font-extrabold text-slate-900 dark:text-white line-clamp-2">${circ.title}</h3></div>
                                    <p class="text-[11px] font-bold text-slate-400">${dateStr}</p>
                                </div>
                                <div class="w-8 h-8 rounded-full flex items-center justify-center bg-slate-200 dark:bg-slate-800 text-slate-500 group-open:rotate-180 transition-transform duration-300 shrink-0">
                                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" /></svg>
                                </div>
                            </summary>
                            <div class="p-5 border-t border-slate-200 dark:border-slate-800/60 bg-slate-50/50 dark:bg-slate-950/20">${contentHtml}</div>
                        </details>
                    `;
                });

                if (loadMore) feed.innerHTML += html.join('');
                else feed.innerHTML = html.join('');
                
                initializeMotionFX();
            } catch (err) {
                console.error("Error fetching circulars:", err);
                document.getElementById('circulars-feed').innerHTML = emptyState("Failed to load circulars. Please check configuration.");
            }
        }

        function toggleCircularsFees() {
            circulars_show_fees = !circulars_show_fees;
            const btn = document.getElementById('toggle-fees-btn');
            if (circulars_show_fees) {
                btn.innerHTML = `<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2m7-2a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>Exclude Fee-Related Circulars`;
                btn.classList.remove('accent-text'); btn.classList.add('text-red-500');
            } else {
                btn.innerHTML = `<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>Include Fee-Related Circulars`;
                btn.classList.remove('text-red-500'); btn.classList.add('accent-text');
            }
            fetchCirculars(false); 
        }

        // --- Announcements ---
        async function fetchAnnouncements() {
            const res = await fetch(`${API_BASE}/api/announcements`); const data = await res.json();
            const feed = document.getElementById('alerts-feed');
            if(data.length > 0) document.getElementById('alert-badge').classList.remove('hidden');
            else { feed.innerHTML = `<div class="text-center py-6 text-sm text-slate-400 font-bold">You're all caught up!</div>`; return; }
            feed.innerHTML = data.map(a => ` <div class="p-3 rounded-xl bg-slate-50 dark:bg-slate-800/50 border border-slate-100 dark:border-slate-800 border-l-4 ${a.type === 'urgent' ? 'border-l-red-500' : 'border-l-brand-500'}"> <div class="flex justify-between items-start mb-1"> <h4 class="font-bold text-sm text-slate-900 dark:text-white line-clamp-1">${a.title}</h4> </div> <p class="text-xs text-slate-500 dark:text-slate-400 line-clamp-2">${a.content}</p> </div> `).join('');
        }
    </script>
</body>
</html>
"""
from fastapi.responses import HTMLResponse

    
@app.get("/", response_class=HTMLResponse)
def index():
    return HTML_CONTENT

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=10000)
