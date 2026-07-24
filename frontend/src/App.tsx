import { useState, useEffect } from 'react';
import {
  Activity,
  AlertTriangle,
  CheckCircle,
  Cpu,
  FileText,
  Heart,
  LayoutDashboard,
  ListVideo,
  Settings as SettingsIcon,
  Users,
  type LucideIcon,
} from 'lucide-react';
import {
  Claims,
  ContentList,
  Creators,
  Dashboard,
  Notes,
  Processing,
  Review,
  Settings,
} from './pages/AllPages';

type PageId =
  | 'dashboard'
  | 'creators'
  | 'content'
  | 'processing'
  | 'notes'
  | 'review'
  | 'claims'
  | 'settings';

interface NavItem {
  id: PageId;
  label: string;
  icon: LucideIcon;
}

const NAV_ITEMS: NavItem[] = [
  { id: 'dashboard',  label: 'Dashboard',  icon: LayoutDashboard },
  { id: 'creators',   label: '创作号',     icon: Users },
  { id: 'content',    label: '内容清单',   icon: ListVideo },
  { id: 'processing', label: '处理队列',   icon: Cpu },
  { id: 'notes',      label: '笔记',       icon: FileText },
  { id: 'review',     label: '审查',       icon: CheckCircle },
  { id: 'claims',     label: '待验证',     icon: AlertTriangle },
  { id: 'settings',   label: '设置',       icon: SettingsIcon },
];

const PAGE_TITLES: Record<PageId, string> = {
  dashboard:  'Dashboard 仪表盘',
  creators:   '创作号管理',
  content:    '内容清单',
  processing: '处理队列',
  notes:      '笔记浏览',
  review:     '笔记审查',
  claims:     '待验证声明',
  settings:   '全局设置',
};

const APP_VERSION = 'v3.0.0';

export default function App() {
  const [page, setPage] = useState<PageId>('dashboard');
  const [healthy, setHealthy] = useState<boolean | null>(null);

  useEffect(() => {
    let alive = true;
    const check = async () => {
      try {
        const r = await fetch('/api/health');
        if (alive) setHealthy(r.ok);
      } catch {
        if (alive) setHealthy(false);
      }
    };
    check();
    const t = setInterval(check, 30000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);

  const renderPage = () => {
    switch (page) {
      case 'dashboard':  return <Dashboard />;
      case 'creators':   return <Creators />;
      case 'content':    return <ContentList />;
      case 'processing': return <Processing />;
      case 'notes':      return <Notes />;
      case 'review':     return <Review />;
      case 'claims':     return <Claims />;
      case 'settings':   return <Settings />;
      default:           return null;
    }
  };

  return (
    <div className="flex min-h-screen">
      <aside className="fixed left-0 top-0 bottom-0 w-60 bg-slate-900 border-r border-slate-800 flex flex-col z-20">
        <div className="p-5 border-b border-slate-800">
          <div className="flex items-center gap-2">
            <Activity className="text-blue-400" size={22} />
            <span className="font-bold text-white">内容策展</span>
          </div>
          <p className="text-xs text-slate-500 mt-1">Content Curator</p>
        </div>
        <nav className="flex-1 overflow-y-auto p-3 space-y-1">
          {NAV_ITEMS.map((item) => {
            const Ico = item.icon;
            return (
              <button
                key={item.id}
                type="button"
                className={`nav-link w-full text-left ${page === item.id ? 'active' : 'text-slate-300'}`}
                onClick={() => setPage(item.id)}
              >
                <Ico size={18} />
                <span>{item.label}</span>
              </button>
            );
          })}
        </nav>
      </aside>

      <div className="flex-1 flex flex-col ml-60 min-w-0">
        <header className="h-14 border-b border-slate-800 bg-slate-900/50 backdrop-blur flex items-center justify-between px-6 sticky top-0 z-10">
          <h1 className="text-lg font-semibold text-white">{PAGE_TITLES[page]}</h1>
          <div className="flex items-center gap-2 text-sm">
            {healthy === null ? (
              <span className="badge badge-gray flex items-center gap-1">
                <Heart size={12} /> 检查中
              </span>
            ) : healthy ? (
              <span className="badge badge-green flex items-center gap-1">
                <Heart size={12} /> 在线
              </span>
            ) : (
              <span className="badge badge-red flex items-center gap-1">
                <Heart size={12} /> 离线
              </span>
            )}
          </div>
        </header>

        <main className="flex-1 p-6 overflow-auto">
          {renderPage()}
        </main>

        <footer className="border-t border-slate-800 px-6 py-3 text-xs text-slate-500 flex items-center justify-between">
          <span>Content Curator {APP_VERSION}</span>
          <span>© {new Date().getFullYear()}</span>
        </footer>
      </div>
    </div>
  );
}
