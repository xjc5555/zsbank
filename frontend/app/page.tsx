"use client";

import {
  ArrowUp,
  Bot,
  CalendarHeart,
  ChevronDown,
  ChevronUp,
  Coffee,
  Pencil,
  PiggyBank,
  Plus,
  ShieldAlert,
  Sparkles,
  WalletCards,
  X,
} from "lucide-react";
import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import dynamic from "next/dynamic";

const PieChart = dynamic(() => import("recharts").then((mod) => mod.PieChart), { ssr: false });
const Pie = dynamic(() => import("recharts").then((mod) => mod.Pie), { ssr: false });
const Cell = dynamic(() => import("recharts").then((mod) => mod.Cell), { ssr: false });
const ResponsiveContainer = dynamic(() => import("recharts").then((mod) => mod.ResponsiveContainer), { ssr: false });
const Tooltip = dynamic(() => import("recharts").then((mod) => mod.Tooltip), { ssr: false });

// ─────────────────── 类型 ───────────────────

type ChatRole = "user" | "assistant";

type ChatMessage = {
  role: ChatRole;
  content: string;
};

type WishlistItem = {
  id: string;
  name: string;
  target_amount: number;
  saved_amount: number;
  months: number;
};

type ExpenseItem = {
  amount: number;
  category: string;
  note: string;
};

type FinanceProfile = {
  risk_level: string;
  monthly_income: number;
  has_emergency_fund: boolean;
  suggestion: string;
  completed: boolean;
  step: number;
};

type ChatResponse = {
  reply: string;
  intent: string;
  risk_flag: boolean;
  budget_total: number;
  budget_left: number;
  wishlists: WishlistItem[];
  active_wishlist_index: number;
  expense_records: ExpenseItem[];
  finance_profile: FinanceProfile;
  messages: ChatMessage[];
  llm_api_key_configured: boolean;
};

// ─────────────────── 常量 ───────────────────

const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL ?? "https://zsbank-production.up.railway.app";

const STORAGE_KEY = "finbuddy_state_v2";

const starterMessages: ChatMessage[] = [
  {
    role: "assistant",
    content:
      "嗨，我是你的财搭子！今天想记一笔账、拆一个心愿，还是问问某个理财概念？有啥赚钱机会不确定靠不靠谱，也可以先丢给我看看～",
  },
];

// 快捷词分组
const quickPromptGroups = [
  {
    label: "记账",
    prompts: ["今天买奶茶花了18元", "午饭吃了26元", "打车花了15块"],
  },
  {
    label: "心愿",
    prompts: ["我想攒钱买电脑", "今天往心愿里存了200元"],
  },
  {
    label: "理财",
    prompts: [
      "货币基金是什么",
      "花呗和信用卡有什么区别",
      "定期存款和余额宝哪个好",
      "应急储蓄应该存多少",
    ],
  },
  {
    label: "测评",
    prompts: ["帮我做个理财测评", "我该怎么理财"],
  },
  {
    label: "风险",
    prompts: ["有人让我做兼职刷单说高收益"],
  },
];

const PIE_COLORS = ["#12b892", "#36d1a8", "#78e9c7", "#f59e0b", "#6366f1", "#f43f5e", "#8b5cf6"];

const CATEGORY_EMOJI: Record<string, string> = {
  餐饮: "🍜",
  交通: "🚇",
  学习: "📚",
  数码: "💻",
  娱乐: "🎮",
  购物: "🛍️",
  医疗: "💊",
  日常消费: "💰",
};

// ─────────────────── 工具函数 ───────────────────

function formatMoney(value: number) {
  return new Intl.NumberFormat("zh-CN", {
    style: "currency",
    currency: "CNY",
    maximumFractionDigits: 0,
  }).format(value);
}

function calcProgress(saved: number, target: number): number {
  if (target <= 0) return 0;
  return Math.min(100, Math.round((saved / target) * 100));
}

function calcMonthlyNeeded(item: WishlistItem): number {
  const remaining = Math.max(0, item.target_amount - item.saved_amount);
  return Math.ceil((remaining / (item.months || 1)) * 100) / 100;
}

// 从 localStorage 加载持久化状态
const defaultFinanceProfile: FinanceProfile = {
  risk_level: "",
  monthly_income: 0,
  has_emergency_fund: false,
  suggestion: "",
  completed: false,
  step: 0,
};

type PersistedState = {
  messages: ChatMessage[];
  budgetTotal: number;
  budgetLeft: number;
  wishlists: WishlistItem[];
  activeWishlistIndex: number;
  expenseRecords: ExpenseItem[];
  intent: string;
  riskFlag: boolean;
  financeProfile: FinanceProfile;
};

function loadState(): PersistedState {
  const defaults: PersistedState = {
    messages: starterMessages,
    budgetTotal: 1500,
    budgetLeft: 1500,
    wishlists: [],
    activeWishlistIndex: 0,
    expenseRecords: [],
    intent: "日常闲聊",
    riskFlag: false,
    financeProfile: defaultFinanceProfile,
  };
  if (typeof window === "undefined") return defaults;
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw) as PersistedState;
      return { ...defaults, ...parsed };
    }
  } catch {
    /* ignore */
  }
  return defaults;
}

// SSR 安全的默认状态（服务端和客户端第一次渲染必须完全一致）
const SSR_DEFAULTS: PersistedState = {
  messages: starterMessages,
  budgetTotal: 1500,
  budgetLeft: 1500,
  wishlists: [],
  activeWishlistIndex: 0,
  expenseRecords: [],
  intent: "日常闲聊",
  riskFlag: false,
  financeProfile: defaultFinanceProfile,
};

// ─────────────────── 主组件 ───────────────────

export default function Home() {
  // 始终用固定默认值初始化，避免 SSR/CSR hydration 不匹配
  const [messages, setMessages] = useState<ChatMessage[]>(SSR_DEFAULTS.messages);
  const [input, setInput] = useState("");
  const [budgetTotal, setBudgetTotal] = useState(SSR_DEFAULTS.budgetTotal);
  const [budgetLeft, setBudgetLeft] = useState(SSR_DEFAULTS.budgetLeft);
  const [wishlists, setWishlists] = useState<WishlistItem[]>(SSR_DEFAULTS.wishlists);
  const [activeWishlistIndex, setActiveWishlistIndex] = useState(SSR_DEFAULTS.activeWishlistIndex);
  const [expenseRecords, setExpenseRecords] = useState<ExpenseItem[]>(SSR_DEFAULTS.expenseRecords);
  const [intent, setIntent] = useState(SSR_DEFAULTS.intent);
  const [riskFlag, setRiskFlag] = useState(SSR_DEFAULTS.riskFlag);
  const [financeProfile, setFinanceProfile] = useState<FinanceProfile>(SSR_DEFAULTS.financeProfile);
  const [isLoading, setIsLoading] = useState(false);
  // hydrated 为 true 后才渲染依赖 localStorage 的内容
  const [hydrated, setHydrated] = useState(false);

  // UI 状态
  const [showStats, setShowStats] = useState(false);
  const [showBudgetEdit, setShowBudgetEdit] = useState(false);
  const [budgetInput, setBudgetInput] = useState("");
  const [activeQuickGroup, setActiveQuickGroup] = useState(0);
  const [showWishEdit, setShowWishEdit] = useState(false);
  const [wishInput, setWishInput] = useState("");

  const messagesEndRef = useRef<HTMLDivElement>(null);

  // ── 客户端挂载后从 localStorage 恢复持久化状态 ──
  useEffect(() => {
    const saved = loadState();
    setMessages(saved.messages);
    setBudgetTotal(saved.budgetTotal);
    setBudgetLeft(saved.budgetLeft);
    setWishlists(saved.wishlists);
    setActiveWishlistIndex(saved.activeWishlistIndex);
    setExpenseRecords(saved.expenseRecords);
    setIntent(saved.intent);
    setRiskFlag(saved.riskFlag);
    setFinanceProfile(saved.financeProfile ?? defaultFinanceProfile);
    setHydrated(true);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── 持久化：每次状态更新都写入 localStorage（hydration 完成后才写）──
  useEffect(() => {
    if (!hydrated) return;
    const state: PersistedState = {
      messages,
      budgetTotal,
      budgetLeft,
      wishlists,
      activeWishlistIndex,
      expenseRecords,
      intent,
      riskFlag,
      financeProfile,
    };
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  }, [hydrated, messages, budgetTotal, budgetLeft, wishlists, activeWishlistIndex, expenseRecords, intent, riskFlag, financeProfile]);

  // ── 消息自动滚动 ──
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isLoading]);

  // ── 消费分类统计（用于饼图） ──
  const categoryStats = useMemo(() => {
    const map: Record<string, number> = {};
    for (const rec of expenseRecords) {
      map[rec.category] = (map[rec.category] ?? 0) + rec.amount;
    }
    return Object.entries(map)
      .map(([name, value]) => ({ name, value: Math.round(value * 100) / 100 }))
      .sort((a, b) => b.value - a.value);
  }, [expenseRecords]);

  const totalSpent = useMemo(
    () => expenseRecords.reduce((sum, r) => sum + r.amount, 0),
    [expenseRecords],
  );

  // ── 预算比例 ──
  const budgetUsedRatio = budgetTotal > 0 ? Math.min(1, (budgetTotal - budgetLeft) / budgetTotal) : 0;
  const budgetWarning = budgetLeft <= 300 && budgetLeft > 0;
  const budgetDanger = budgetLeft <= 0;

  // ── 发送消息 ──
  const sendMessage = useCallback(
    async (nextInput?: string) => {
      const content = (nextInput ?? input).trim();
      if (!content || isLoading) return;

      const history = messages;
      setInput("");
      setIsLoading(true);
      setMessages([...history, { role: "user", content }]);

      try {
        const response = await fetch(`${backendUrl}/chat`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            message: content,
            history,
            budget_total: budgetTotal,
            budget_left: budgetLeft,
            wishlists,
            active_wishlist_index: activeWishlistIndex,
            expense_records: expenseRecords,
            finance_profile: financeProfile,
          }),
        });

        if (!response.ok) throw new Error(`Backend responded with ${response.status}`);

        const data = (await response.json()) as ChatResponse;
        setMessages(data.messages);
        setBudgetTotal(data.budget_total);
        setBudgetLeft(data.budget_left);
        setWishlists(data.wishlists);
        setActiveWishlistIndex(data.active_wishlist_index);
        setExpenseRecords(data.expense_records);
        setIntent(data.intent);
        setRiskFlag(data.risk_flag);
        if (data.finance_profile) setFinanceProfile(data.finance_profile);
      } catch {
        setMessages((current) => [
          ...current,
          {
            role: "assistant",
            content: "后端搭子暂时没连上，先确认 FastAPI 已在 localhost:8000 启动～",
          },
        ]);
      } finally {
        setIsLoading(false);
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [input, isLoading, messages, budgetTotal, budgetLeft, wishlists, activeWishlistIndex, expenseRecords, financeProfile],
  );

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void sendMessage();
  }

  // ── 手动设置预算 ──
  function applyBudgetEdit() {
    const val = parseFloat(budgetInput);
    if (!isNaN(val) && val > 0) {
      setBudgetTotal(val);
      setBudgetLeft(val);
      void sendMessage(`预算设为${val}元`);
    }
    setShowBudgetEdit(false);
    setBudgetInput("");
  }

  // ── 心愿快捷输入 ──
  function applyWishEdit() {
    const text = wishInput.trim();
    if (text) {
      void sendMessage(text);
    }
    setShowWishEdit(false);
    setWishInput("");
  }

  // ── 重置数据 ──
  async function handleReset() {
    if (!window.confirm("确定要清空所有记录吗？")) return;
    // 通知后端清除会话（后端无状态，收到即确认）
    try {
      await fetch(`${backendUrl}/reset`, { method: "POST" });
    } catch {
      /* 后端不可达时仍允许前端重置 */
    }
    setMessages(starterMessages);
    setBudgetTotal(1500);
    setBudgetLeft(1500);
    setWishlists([]);
    setActiveWishlistIndex(0);
    setExpenseRecords([]);
    setIntent("日常闲聊");
    setRiskFlag(false);
    setFinanceProfile(defaultFinanceProfile);
    localStorage.removeItem(STORAGE_KEY);
  }

  // ── 当前活跃心愿 ──
  const activeWishlist = wishlists[activeWishlistIndex] ?? null;

  return (
    <main className="min-h-screen px-4 py-5 text-slate-950">
      <section className="mx-auto flex min-h-[calc(100vh-2.5rem)] w-full max-w-md flex-col overflow-hidden rounded-[2rem] border border-white/70 bg-white/75 shadow-soft backdrop-blur">

        {/* ── Header ── */}
        <header className="relative overflow-hidden bg-gradient-to-br from-mint-300 via-mint-200 to-white px-5 pb-5 pt-5">
          <div className="absolute right-4 top-4 h-20 w-20 rounded-full bg-white/40 blur-2xl" />
          <div className="relative flex items-center justify-between">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.24em] text-emerald-700">FinBuddy</p>
              <h1 className="mt-1 text-3xl font-black tracking-tight text-slate-950">财搭子</h1>
            </div>
            <div className="flex items-center gap-2">
              <button
                className="rounded-xl bg-white/60 px-3 py-1.5 text-xs font-semibold text-slate-500 hover:bg-white/80"
                onClick={handleReset}
                type="button"
              >
                重置
              </button>
              <div className="rounded-2xl bg-white/80 p-3 shadow-sm">
                <Sparkles className="h-6 w-6 text-emerald-600" />
              </div>
            </div>
          </div>
          <p className="relative mt-2 text-sm leading-6 text-slate-700">
            不说教、不卖产品，只陪你把日常预算、心愿计划和风险提醒放在一个轻松的小空间里。
          </p>
        </header>

        {/* ── 状态卡片区 ── */}
        <section className="grid grid-cols-2 gap-3 px-4 pt-4">
          {/* 预算卡片 */}
          <div
            className={`rounded-3xl p-4 shadow-sm ring-1 ${
              budgetDanger
                ? "bg-red-50 ring-red-200"
                : budgetWarning
                  ? "bg-amber-50 ring-amber-200"
                  : "bg-white ring-emerald-100"
            }`}
          >
            <div className="flex items-center justify-between">
              <div
                className={`flex items-center gap-1.5 text-xs font-semibold ${
                  budgetDanger ? "text-red-600" : budgetWarning ? "text-amber-600" : "text-emerald-700"
                }`}
              >
                <WalletCards className="h-4 w-4" />
                本月预算
              </div>
              <button
                className="rounded-full p-1 text-slate-400 hover:bg-slate-100"
                onClick={() => setShowBudgetEdit((v) => !v)}
                type="button"
              >
                <Pencil className="h-3.5 w-3.5" />
              </button>
            </div>
            <p className={`mt-2 text-2xl font-black ${budgetDanger ? "text-red-600" : budgetWarning ? "text-amber-600" : ""}`}>
              {formatMoney(budgetLeft)}
            </p>
            {/* 预算进度条 */}
            <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-slate-100">
              <div
                className={`h-1.5 rounded-full transition-all ${
                  budgetDanger ? "bg-red-500" : budgetWarning ? "bg-amber-400" : "bg-emerald-400"
                }`}
                style={{ width: `${(1 - budgetUsedRatio) * 100}%` }}
              />
            </div>
            <p className="mt-1 text-xs text-slate-400">共 {formatMoney(budgetTotal)}</p>
          </div>

          {/* 心愿卡片 */}
          <button
            className="rounded-3xl bg-gradient-to-br from-emerald-400 via-teal-400 to-cyan-400 p-4 text-white shadow-sm transition-all hover:brightness-105 active:scale-[0.98] text-left w-full"
            onClick={() => setShowWishEdit((v) => !v)}
            type="button"
          >
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-1.5 text-xs font-semibold text-white/90">
                <CalendarHeart className="h-4 w-4" />
                {activeWishlist ? activeWishlist.name : "心愿"}
              </div>
              <div className="flex items-center gap-1.5">
                {wishlists.length > 1 && (
                  <span className="rounded-full bg-white/25 px-1.5 py-0.5 text-xs text-white/90">
                    {activeWishlistIndex + 1}/{wishlists.length}
                  </span>
                )}
                <Pencil className="h-3.5 w-3.5 text-white/70" />
              </div>
            </div>
            {activeWishlist ? (
              <>
                <p className="mt-2 text-2xl font-black text-white">{calcProgress(activeWishlist.saved_amount, activeWishlist.target_amount)}%</p>
                <div className="mt-2 h-1.5 rounded-full bg-white/30">
                  <div
                    className="h-1.5 rounded-full bg-white transition-all"
                    style={{ width: `${calcProgress(activeWishlist.saved_amount, activeWishlist.target_amount)}%` }}
                  />
                </div>
                <p className="mt-1 text-xs text-white/75">
                  月存 {formatMoney(calcMonthlyNeeded(activeWishlist))} · 目标 {formatMoney(activeWishlist.target_amount)}
                </p>
              </>
            ) : (
              <p className="mt-3 text-sm text-white/80">点击输入心愿，我帮你拆计划 ✨</p>
            )}
          </button>
        </section>

        {/* ── 心愿快捷输入弹出框 ── */}
        {showWishEdit && (
          <div className="mx-4 mt-3 rounded-2xl border border-teal-100 bg-white p-3 shadow-sm">
            <p className="mb-2 text-xs font-semibold text-slate-600">告诉我你的心愿</p>
            <div className="flex gap-2">
              <input
                autoFocus
                className="min-w-0 flex-1 rounded-xl border border-slate-200 px-3 py-2 text-sm outline-none focus:border-teal-400"
                onChange={(e) => setWishInput(e.target.value)}
                placeholder="如：12个月攒6000买耳机，或：今天存了200"
                type="text"
                value={wishInput}
                onKeyDown={(e) => e.key === "Enter" && applyWishEdit()}
              />
              <button
                className="rounded-xl bg-teal-500 px-4 py-2 text-sm font-semibold text-white"
                onClick={applyWishEdit}
                type="button"
              >
                确认
              </button>
              <button
                className="rounded-xl border border-slate-200 px-3 py-2 text-sm text-slate-500"
                onClick={() => setShowWishEdit(false)}
                type="button"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
          </div>
        )}

        {/* ── 预算编辑弹出框 ── */}
        {showBudgetEdit && (
          <div className="mx-4 mt-3 rounded-2xl border border-emerald-100 bg-white p-3 shadow-sm">
            <p className="mb-2 text-xs font-semibold text-slate-600">设置本月预算</p>
            <div className="flex gap-2">
              <input
                autoFocus
                className="min-w-0 flex-1 rounded-xl border border-slate-200 px-3 py-2 text-sm outline-none focus:border-emerald-400"
                onChange={(e) => setBudgetInput(e.target.value)}
                placeholder="输入金额，如 2000"
                type="number"
                value={budgetInput}
                onKeyDown={(e) => e.key === "Enter" && applyBudgetEdit()}
              />
              <button
                className="rounded-xl bg-emerald-500 px-4 py-2 text-sm font-semibold text-white"
                onClick={applyBudgetEdit}
                type="button"
              >
                确认
              </button>
              <button
                className="rounded-xl border border-slate-200 px-3 py-2 text-sm text-slate-500"
                onClick={() => setShowBudgetEdit(false)}
                type="button"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
          </div>
        )}

        {/* ── 多心愿列表（展开/折叠） ── */}
        {wishlists.length > 0 && (
          <div className="mx-4 mt-3">
            <button
              className="flex w-full items-center justify-between rounded-2xl border border-emerald-100 bg-mint-50/80 px-3 py-2 text-xs font-semibold text-emerald-700"
              onClick={() => setShowStats((v) => !v)}
              type="button"
            >
              <span className="flex items-center gap-1.5">
                <PiggyBank className="h-4 w-4" />
                全部心愿（{wishlists.length}）
              </span>
              {showStats ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
            </button>

            {showStats && (
              <div className="mt-2 space-y-2">
                {/* 多心愿卡片 */}
                {wishlists.map((w, idx) => (
                  <button
                    key={w.id}
                    className={`w-full rounded-2xl border p-3 text-left shadow-sm transition-all ${
                      idx === activeWishlistIndex
                        ? "border-emerald-300 bg-emerald-50"
                        : "border-slate-100 bg-white hover:border-emerald-200"
                    }`}
                    onClick={() => setActiveWishlistIndex(idx)}
                    type="button"
                  >
                    <div className="flex items-center justify-between">
                      <span className="text-sm font-semibold text-slate-800">{w.name}</span>
                      <span className="text-xs text-slate-400">
                        {formatMoney(w.saved_amount)} / {formatMoney(w.target_amount)}
                      </span>
                    </div>
                    <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-slate-100">
                      <div
                        className="h-1.5 rounded-full bg-emerald-400 transition-all"
                        style={{ width: `${calcProgress(w.saved_amount, w.target_amount)}%` }}
                      />
                    </div>
                    <p className="mt-1 text-xs text-slate-400">
                      {calcProgress(w.saved_amount, w.target_amount)}% · 每月存 {formatMoney(calcMonthlyNeeded(w))} · {w.months}个月
                    </p>
                  </button>
                ))}

                {/* 消费统计区 */}
                {expenseRecords.length > 0 && (
                  <div className="rounded-2xl border border-slate-100 bg-white p-3 shadow-sm">
                    <p className="mb-3 text-xs font-semibold text-slate-600">
                      本月消费统计 · 共 {formatMoney(totalSpent)}
                    </p>

                    {/* 饼图 */}
                    <div className="h-36">
                      <ResponsiveContainer width="100%" height="100%">
                        <PieChart>
                          <Pie
                            data={categoryStats}
                            cx="50%"
                            cy="50%"
                            innerRadius={36}
                            outerRadius={60}
                            paddingAngle={2}
                            dataKey="value"
                          >
                            {categoryStats.map((entry, index) => (
                              <Cell key={entry.name} fill={PIE_COLORS[index % PIE_COLORS.length]} />
                            ))}
                          </Pie>
                          <Tooltip
                            formatter={(value) => [formatMoney(Number(value)), "消费"]}
                            contentStyle={{
                              borderRadius: "12px",
                              fontSize: "12px",
                              border: "1px solid #d1fae5",
                            }}
                          />
                        </PieChart>
                      </ResponsiveContainer>
                    </div>

                    {/* 分类列表 */}
                    <div className="mt-2 space-y-1.5">
                      {categoryStats.map((stat, idx) => (
                        <div key={stat.name} className="flex items-center gap-2">
                          <div
                            className="h-2.5 w-2.5 shrink-0 rounded-full"
                            style={{ backgroundColor: PIE_COLORS[idx % PIE_COLORS.length] }}
                          />
                          <span className="text-xs text-slate-600">
                            {CATEGORY_EMOJI[stat.name] ?? "💰"} {stat.name}
                          </span>
                          <div className="flex-1" />
                          <span className="text-xs font-semibold text-slate-800">{formatMoney(stat.value)}</span>
                          <span className="w-8 text-right text-xs text-slate-400">
                            {totalSpent > 0 ? Math.round((stat.value / totalSpent) * 100) : 0}%
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        {/* ── 理财测评结果卡片（测评完成后展示） ── */}
        {financeProfile.completed && financeProfile.risk_level && (
          <div className="mx-4 mt-3 rounded-3xl border border-violet-100 bg-violet-50/80 p-4 shadow-sm">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="text-lg">📊</span>
                <span className="text-sm font-bold text-violet-700">理财画像</span>
              </div>
              <span className="rounded-full bg-violet-100 px-2.5 py-1 text-xs font-bold text-violet-700">
                {financeProfile.risk_level}
              </span>
            </div>
            <div className="mt-2 flex gap-3 text-xs text-violet-600">
              <span>💰 月均 ¥{financeProfile.monthly_income}</span>
              <span>{financeProfile.has_emergency_fund ? "✅ 有应急储蓄" : "🔴 待建立应急储蓄"}</span>
            </div>
            <button
              className="mt-2 text-xs text-violet-400 underline"
              onClick={() => void sendMessage("理财测评")}
              type="button"
            >
              重新测评
            </button>
          </div>
        )}

        {/* ── 理财测评入口（未完成时展示引导卡片） ── */}
        {!financeProfile.completed && financeProfile.step === 0 && (
          <div className="mx-4 mt-3 rounded-3xl border border-violet-100 bg-gradient-to-r from-violet-50 to-white p-4 shadow-sm">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="text-lg">🧭</span>
                <span className="text-sm font-bold text-violet-700">理财测评</span>
              </div>
              <button
                className="rounded-full bg-violet-500 px-3 py-1.5 text-xs font-bold text-white shadow-sm hover:bg-violet-600"
                onClick={() => void sendMessage("帮我做个理财测评")}
                type="button"
              >
                开始测评 →
              </button>
            </div>
            <p className="mt-1.5 text-xs text-violet-500">
              3个问题，了解你的风险偏好，获取个性化入门理财建议
            </p>
          </div>
        )}

        {/* ── 意图 & 风控状态条 ── */}
        <section className="mx-4 mt-3 rounded-3xl border border-emerald-100 bg-mint-50/80 p-3">
          <div className="flex items-center justify-between text-xs">
            <span className="flex items-center gap-2 font-semibold text-emerald-700">
              <Plus className="h-4 w-4" />
              当前意图：{intent}
            </span>
            <span
              className={`rounded-full px-2 py-1 font-semibold ${
                riskFlag ? "bg-red-100 text-red-600" : "bg-white text-emerald-700"
              }`}
            >
              {riskFlag ? "⚠️ 风险接管中" : "✓ 状态安全"}
            </span>
          </div>
        </section>

        {/* ── 聊天区 ── */}
        <section className="flex-1 space-y-3 overflow-y-auto px-4 py-4">
          {messages.map((message, index) => {
            const isUser = message.role === "user";
            const isLastAssistant = !isUser && index === messages.length - 1;
            return (
              <div key={`${message.role}-${index}`} className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
                <div
                  className={`max-w-[82%] rounded-3xl px-4 py-3 text-sm leading-6 shadow-sm ${
                    isUser
                      ? "rounded-br-md bg-slate-950 text-white"
                      : "rounded-bl-md bg-white text-slate-700 ring-1 ring-emerald-100"
                  }`}
                >
                  {!isUser && (
                    <div className="mb-1.5 flex items-center gap-2 text-xs font-bold text-emerald-700">
                      {riskFlag && isLastAssistant ? (
                        <ShieldAlert className="h-4 w-4 text-red-500" />
                      ) : (
                        <Bot className="h-4 w-4" />
                      )}
                      财搭子
                    </div>
                  )}
                  <span style={{ whiteSpace: "pre-wrap" }}>{message.content}</span>
                </div>
              </div>
            );
          })}

          {isLoading && (
            <div className="flex justify-start">
              <div className="rounded-3xl rounded-bl-md bg-white px-4 py-3 text-sm text-slate-400 ring-1 ring-emerald-100">
                <span className="inline-flex items-center gap-1">
                  <span className="animate-bounce">·</span>
                  <span className="animate-bounce" style={{ animationDelay: "0.15s" }}>·</span>
                  <span className="animate-bounce" style={{ animationDelay: "0.3s" }}>·</span>
                </span>
              </div>
            </div>
          )}

          {/* 自动滚动锚点 */}
          <div ref={messagesEndRef} />
        </section>

        {/* ── 输入区 ── */}
        <section className="space-y-3 border-t border-emerald-100 bg-white/80 p-4">
          {/* 快捷词分组 Tab */}
          <div className="space-y-2">
            <div className="flex gap-1.5 overflow-x-auto pb-0.5">
              {quickPromptGroups.map((group, idx) => (
                <button
                  key={group.label}
                  className={`shrink-0 rounded-full px-3 py-1 text-xs font-semibold transition-colors ${
                    activeQuickGroup === idx
                      ? "bg-emerald-500 text-white"
                      : "border border-emerald-100 bg-mint-50 text-emerald-700 hover:bg-mint-100"
                  }`}
                  onClick={() => setActiveQuickGroup(idx)}
                  type="button"
                >
                  {group.label}
                </button>
              ))}
            </div>
            <div className="flex gap-2 overflow-x-auto pb-1">
              {quickPromptGroups[activeQuickGroup]?.prompts.map((prompt) => (
                <button
                  key={prompt}
                  className="shrink-0 rounded-full border border-emerald-100 bg-white px-3 py-2 text-xs text-slate-600 hover:bg-mint-50"
                  onClick={() => void sendMessage(prompt)}
                  type="button"
                >
                  {prompt}
                </button>
              ))}
            </div>
          </div>

          <form className="flex items-center gap-2 rounded-3xl bg-slate-100 p-2" onSubmit={handleSubmit}>
            <div className="rounded-full bg-white p-2 text-emerald-600">
              <Coffee className="h-5 w-5" />
            </div>
            <input
              className="min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-slate-400"
              onChange={(event) => setInput(event.target.value)}
              placeholder="比如：今天午饭花了26元"
              value={input}
            />
            <button
              className="rounded-full bg-emerald-500 p-3 text-white shadow-sm disabled:bg-slate-300"
              disabled={isLoading || !input.trim()}
              type="submit"
            >
              <ArrowUp className="h-5 w-5" />
            </button>
          </form>
        </section>
      </section>
    </main>
  );
}
