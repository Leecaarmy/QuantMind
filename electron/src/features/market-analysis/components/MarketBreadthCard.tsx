import React from 'react';
import { Flame, ShieldAlert, TrendingUp, TrendingDown, Layers } from 'lucide-react';

interface MarketBreadthCardProps {
  className?: string;
  advanceCount?: number;
  declineCount?: number;
  flatCount?: number;
  limitUpCount?: number;
  limitDownCount?: number;
  totalTurnoverYi?: number;
  profitEffect?: number;
  limitUpBrokenRatio?: number;
}

export const MarketBreadthCard: React.FC<MarketBreadthCardProps> = ({
  className = '',
  advanceCount = 3120,
  declineCount = 1850,
  flatCount = 380,
  limitUpCount = 68,
  limitDownCount = 7,
  totalTurnoverYi = 9535.9,
  profitEffect = 62.8,
  limitUpBrokenRatio = 14.2,
}) => {
  const total = advanceCount + declineCount + flatCount || 1;
  const advPct = Math.round((advanceCount / total) * 100);
  const decPct = Math.round((declineCount / total) * 100);
  const flatPct = Math.max(0, 100 - advPct - decPct);

  return (
    <div className={`bg-white/90 backdrop-blur-md rounded-2xl p-4 border border-slate-200/80 shadow-sm flex flex-col gap-3 ${className}`}>
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-extrabold text-slate-800 flex items-center gap-1.5">
          <Flame className="w-3.5 h-3.5 text-purple-600" />
          <span>全市场情绪温度计与赚钱效应</span>
        </h3>
        <span className="px-2.5 py-0.5 rounded-full bg-purple-50 text-purple-700 text-[11px] font-bold border border-purple-100 font-mono">
          全市场总成交: ¥{totalTurnoverYi.toLocaleString()} 亿
        </span>
      </div>

      {/* 涨跌家数比例条形图 */}
      <div className="space-y-2">
        <div className="flex items-center justify-between text-xs font-bold">
          <span className="text-red-500 flex items-center gap-1">
            <TrendingUp className="w-3.5 h-3.5" />
            上涨 {advanceCount} 家 ({advPct}%)
          </span>
          <span className="text-slate-400">平盘 {flatCount} 家</span>
          <span className="text-emerald-500 flex items-center gap-1">
            <TrendingDown className="w-3.5 h-3.5" />
            下跌 {declineCount} 家 ({decPct}%)
          </span>
        </div>

        <div className="w-full h-3.5 rounded-full bg-slate-100 overflow-hidden flex items-center p-0.5 border border-slate-200/60">
          <div className="h-full bg-gradient-to-r from-red-500 to-red-400 rounded-l-full transition-all" style={{ width: `${advPct}%` }} />
          <div className="h-full bg-slate-300 transition-all" style={{ width: `${flatPct}%` }} />
          <div className="h-full bg-gradient-to-r from-emerald-400 to-emerald-500 rounded-r-full transition-all" style={{ width: `${decPct}%` }} />
        </div>
      </div>

      {/* 涨停 / 跌停 家数与极点指标 */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-center">
        <div className="bg-red-50/80 p-3 rounded-2xl border border-red-100">
          <div className="text-[11px] text-red-600/80 font-medium">涨停家数</div>
          <div className="text-lg font-extrabold font-mono text-red-600">{limitUpCount} <span className="text-xs font-normal">家</span></div>
        </div>

        <div className="bg-emerald-50/80 p-3 rounded-2xl border border-emerald-100">
          <div className="text-[11px] text-emerald-600/80 font-medium">跌停家数</div>
          <div className="text-lg font-extrabold font-mono text-emerald-600">{limitDownCount} <span className="text-xs font-normal">家</span></div>
        </div>

        <div className="bg-purple-50/80 p-3 rounded-2xl border border-purple-100">
          <div className="text-[11px] text-purple-600/80 font-medium">炸板率</div>
          <div className="text-lg font-extrabold font-mono text-purple-700">{limitUpBrokenRatio}%</div>
        </div>

        <div className="bg-slate-50 p-3 rounded-2xl border border-slate-100">
          <div className="text-[11px] text-slate-500 font-medium">赚钱效应指数</div>
          <div className="text-lg font-extrabold font-mono text-slate-800">{profitEffect} <span className="text-xs font-normal">/ 100</span></div>
        </div>
      </div>
    </div>
  );
};

