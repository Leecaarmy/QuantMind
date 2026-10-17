/**
 * 策略管理模块 - 统一版 (2026-02-14)
 * 
 * 功能：
 * - 统一通过 strategyManagementService 加载远程策略
 * - 编辑跳转至 AI-IDE
 * - 回测跳转至快速回测界面
 */

import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useDispatch } from 'react-redux';
import { motion } from 'framer-motion';
import {
    FileCode,
    Trash2,
    TestTube,
    Search,
    RefreshCw,
    Edit,
    AlertTriangle,
    Star,
} from 'lucide-react';
import { message, Modal } from 'antd';
import { strategyManagementService } from '../../services/strategyManagementService';
import { useBacktestCenterStore } from '../../stores/backtestCenterStore';
import { setCurrentTab } from '../../store/slices/aiStrategySlice';

interface Strategy {
    id: string;
    name: string;
    status: 'draft' | 'repository' | 'live_trading' | 'active' | 'inactive' | 'archived';
    created_at: string;
    updated_at: string;
    is_favorite?: boolean;
    validated_backtest_id?: number;
    promoted_at?: string;
    live_trading_started_at?: string;
    performance_summary?: {
        total_return_pct?: number;
        sharpe_ratio?: number;
        max_drawdown?: number;
    };
}

export const StrategyManagementModule: React.FC = () => {
    const navigate = useNavigate();
    const dispatch = useDispatch();
    const { setActiveModule } = useBacktestCenterStore();
    
    const [strategies, setStrategies] = useState<Strategy[]>([]);
    const [loading, setLoading] = useState(false);
    const [searchTerm, setSearchTerm] = useState('');
    const [deleteModalVisible, setDeleteModalVisible] = useState(false);
    const [selectedStrategy, setSelectedStrategy] = useState<Strategy | null>(null);

    useEffect(() => {
        loadStrategies();
    }, []);

    const normalizeStatus = (status?: string): Strategy['status'] => {
        const value = String(status || '').toLowerCase();
        if (['repository', 'live_trading', 'draft', 'archived'].includes(value)) return value as Strategy['status'];
        if (value === 'active') return 'repository';
        if (value === 'paused' || value === 'inactive') return 'inactive';
        return 'draft';
    };

    const loadStrategies = async () => {
        setLoading(true);
        try {
            const items = await strategyManagementService.loadStrategies();
            const mapped: Strategy[] = items.map((item: any) => ({
                id: item.id,
                name: item.name,
                status: normalizeStatus(item.status),
                created_at: item.created_at || new Date().toISOString(),
                updated_at: item.updated_at || item.created_at || new Date().toISOString(),
                is_favorite: !!item.is_favorite,
                validated_backtest_id: item.validated_backtest_id,
                promoted_at: item.promoted_at,
                live_trading_started_at: item.live_trading_started_at,
                performance_summary: item.performance_summary,
            }));
            setStrategies(mapped);
        } catch (error: any) {
            message.error('加载策略列表失败: ' + error.message);
            setStrategies([]);
        } finally {
            setLoading(false);
        }
    };

    const handleBacktest = (strategy: Strategy) => {
        message.info(`跳转到快速回测: ${strategy.name}`);
        localStorage.setItem('selected_backtest_strategy_id', strategy.id);
        setActiveModule('quick-backtest');
        dispatch(setCurrentTab('backtest' as any));
    };

    const handleEdit = (strategy: Strategy) => {
        if (strategy.status === 'repository') {
            Modal.confirm({
                title: '编辑仓库策略',
                icon: <AlertTriangle className="w-5 h-5 text-orange-500" />,
                content: '编辑仓库策略将自动降级到草稿状态，需要重新回测验证才能再次晋升。',
                okText: '确认编辑',
                onOk: () => {
                    message.success(`正在跳转到 AI-IDE 编辑...`);
                    navigate(`/ai-ide?strategyId=${strategy.id}`);
                },
            });
        } else {
            navigate(`/ai-ide?strategyId=${strategy.id}`);
        }
    };

    const handleDeleteClick = (strategy: Strategy) => {
        setSelectedStrategy(strategy);
        setDeleteModalVisible(true);
    };

    const handleConfirmDelete = async () => {
        if (!selectedStrategy) return;
        try {
            await strategyManagementService.deleteStrategy(selectedStrategy.id);
            message.success(`策略已删除`);
            loadStrategies();
        } catch (error: any) {
            message.error('删除失败: ' + error.message);
        } finally {
            setDeleteModalVisible(false);
            setSelectedStrategy(null);
        }
    };

    const filteredStrategies = strategies
        .filter((s) =>
            s.name.toLowerCase().includes(searchTerm.toLowerCase())
        )
        // 收藏置顶，其次按更新时间倒序
        .sort((a, b) =>
            Number(b.is_favorite ?? false) - Number(a.is_favorite ?? false)
        );

    const getStatusBadge = (status: Strategy['status']) => {
        const configs: any = {
            draft: { bg: 'bg-gray-100', text: 'text-gray-600', label: '草稿' },
            repository: { bg: 'bg-blue-100', text: 'text-blue-600', label: '仓库' },
            live_trading: { bg: 'bg-green-100', text: 'text-green-600', label: '模拟中' },
            inactive: { bg: 'bg-slate-100', text: 'text-slate-400', label: '未激活' },
            archived: { bg: 'bg-rose-100', text: 'text-rose-400', label: '已归档' },
        };
        const config = configs[status] || configs.draft;
        return <span className={`px-2 py-1 rounded-lg text-xs font-semibold ${config.bg} ${config.text}`}>{config.label}</span>;
    };

    return (
        <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.25 }}
            className="h-full flex flex-col bg-white rounded-2xl border border-gray-200 shadow-sm overflow-hidden"
        >
            <div className="px-6 py-4 border-b border-gray-200">
                <div className="flex items-center justify-between mb-4">
                    <div>
                        <p className="text-[11px] font-semibold text-gray-500 uppercase tracking-wider mb-1">Strategy Library</p>
                        <h2 className="text-lg font-bold text-slate-800 tracking-tight">策略管理</h2>
                        <p className="text-sm text-gray-500">查看、编辑与回测验证策略</p>
                    </div>
                    <button onClick={loadStrategies} className="p-2 hover:bg-gray-100 rounded-xl transition-colors">
                        <RefreshCw className={`w-5 h-5 text-gray-600 ${loading ? 'animate-spin' : ''}`} />
                    </button>
                </div>
                <div className="relative">
                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
                    <input
                        type="text"
                        placeholder="搜索策略..."
                        value={searchTerm}
                        onChange={(e) => setSearchTerm(e.target.value)}
                        className="w-full pl-10 pr-4 py-2 border border-gray-200 rounded-xl focus:ring-2 focus:ring-blue-500 outline-none"
                    />
                </div>
            </div>

            <div className="flex-1 overflow-y-auto p-6">
                {loading ? (
                    <div className="flex items-center justify-center h-64 text-gray-400">加载中...</div>
                ) : filteredStrategies.length === 0 ? (
                    <div className="flex flex-col items-center justify-center h-64 text-gray-400">
                        <FileCode className="w-16 h-16 mb-4 opacity-50" />
                        <p>暂无策略</p>
                    </div>
                ) : (
                    <div className="grid grid-cols-1 gap-4">
                        {filteredStrategies.map((strategy) => (
                            <motion.div
                                key={strategy.id}
                                layout
                                whileHover={{ y: -2 }}
                                whileTap={{ scale: 0.995 }}
                                className="p-4 border border-gray-200 rounded-2xl hover:shadow-md transition-shadow bg-white"
                            >
                                <div className="flex items-start justify-between mb-3">
                                    <div className="flex-1">
                                        <div className="flex items-center gap-3 mb-2">
                                            {strategy.is_favorite && (
                                                <Star className="w-4 h-4 text-amber-400" fill="currentColor" />
                                            )}
                                            <h3 className="text-sm font-semibold text-slate-700 tracking-tight">{strategy.name}</h3>
                                            {getStatusBadge(strategy.status)}
                                        </div>
                                        <div className="text-xs text-gray-500">
                                            创建时间: {new Date(strategy.created_at).toLocaleString()}
                                        </div>
                                    </div>
                                </div>
                                <div className="flex items-center gap-2 pt-3 border-t border-gray-100">
                                    <button onClick={() => handleEdit(strategy)} className="flex items-center gap-1 px-3 py-1.5 bg-purple-50 text-purple-600 rounded-lg text-sm">
                                        <Edit className="w-4 h-4" /> 编辑
                                    </button>
                                    <button onClick={() => handleBacktest(strategy)} className="flex items-center gap-1 px-3 py-1.5 bg-blue-50 text-blue-600 rounded-lg text-sm">
                                        <TestTube className="w-4 h-4" /> 回测验证
                                    </button>
                                    <button onClick={() => handleDeleteClick(strategy)} className="flex items-center gap-1 px-3 py-1.5 bg-red-50 text-red-600 rounded-lg text-sm">
                                        <Trash2 className="w-4 h-4" /> 删除
                                    </button>
                                </div>
                            </motion.div>
                        ))}
                    </div>
                )}
            </div>

            <Modal
                title="确认删除"
                open={deleteModalVisible}
                onOk={handleConfirmDelete}
                onCancel={() => setDeleteModalVisible(false)}
                okText="确认删除"
                cancelText="取消"
                okButtonProps={{ danger: true }}
            >
                <p>确定要永久删除策略 "{selectedStrategy?.name}" 吗？</p>
            </Modal>
        </motion.div>
    );
};
