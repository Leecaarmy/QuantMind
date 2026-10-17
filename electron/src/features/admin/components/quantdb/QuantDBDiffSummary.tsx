import React from 'react';
import { Button, Card, Space, Statistic, Tag, Tooltip, Typography } from 'antd';
import {
    CheckCircleFilled,
    CloudSyncOutlined,
    ExclamationCircleFilled,
    QuestionCircleFilled,
    SyncOutlined,
} from '@ant-design/icons';
import { QuantDBDiffResult, QuantDBDatasetDiff } from '../../services/dataPlatformService';
import { HIDDEN_DATASETS } from './utils';

const { Text } = Typography;

interface QuantDBDiffSummaryProps {
    diff: QuantDBDiffResult | null;
    loading: boolean;
    onCheckUpdates: () => void;
    onSyncSelected: (datasets: string[]) => void;
    /** 下方目录实际展示的数据集名集合（已剔除隐藏大类/隐藏集）。
     * 传入后统计与可同步列表只按此集合计算，使上下两处口径一致；
     * 不传时退化为旧行为（全量 + HIDDEN_DATASETS 过滤）。
     * 集合外仍需同步的隐藏集会单独标注条数，不混入统计。 */
    visibleDatasetNames?: Set<string> | null;
}

const STATUS_CONFIG: Record<string, { color: string; label: string; icon: React.ReactNode }> = {
    up_to_date: { color: '#10b981', label: '已最新', icon: <CheckCircleFilled /> },
    updates_available: { color: '#f59e0b', label: '有更新', icon: <ExclamationCircleFilled /> },
    not_synced: { color: '#94a3b8', label: '未同步', icon: <QuestionCircleFilled /> },
    unknown: { color: '#cbd5e1', label: '未知', icon: <QuestionCircleFilled /> },
};

function formatRemoteDate(date: string | null | undefined): string {
    if (!date) return '—';
    const s = String(date);
    if (s.length === 8) return `${s.slice(0, 4)}-${s.slice(4, 6)}-${s.slice(6, 8)}`;
    return s;
}

export const QuantDBDiffSummary: React.FC<QuantDBDiffSummaryProps> = ({
    diff,
    loading,
    onCheckUpdates,
    onSyncSelected,
    visibleDatasetNames = null,
}) => {
    const inScope = (name: string) => !visibleDatasetNames || visibleDatasetNames.has(name);
    const scopedDatasets = diff ? diff.datasets.filter(d => inScope(d.dataset)) : [];

    const summary = React.useMemo(() => {
        const s = { total_datasets: 0, up_to_date: 0, updates_available: 0, not_synced: 0, unknown: 0 };
        for (const d of scopedDatasets) {
            s.total_datasets += 1;
            if (d.status === 'up_to_date') s.up_to_date += 1;
            else if (d.status === 'updates_available') s.updates_available += 1;
            else if (d.status === 'not_synced') s.not_synced += 1;
            else s.unknown += 1;
        }
        return s;
    }, [diff, visibleDatasetNames]);

    const behindDatasets = scopedDatasets.filter(
        d => d.status === 'updates_available' && !HIDDEN_DATASETS.has(d.dataset),
    );
    const notSyncedDatasets = scopedDatasets.filter(
        d => d.status === 'not_synced' && !HIDDEN_DATASETS.has(d.dataset),
    );

    const syncableDatasets = [...behindDatasets, ...notSyncedDatasets];

    // 作用域外（下方列表不展示的隐藏集）仍需同步时，仅标注条数，不混入统计。
    const hiddenSyncable = diff
        ? diff.datasets.filter(
            d => (d.status === 'updates_available' || d.status === 'not_synced') && !inScope(d.dataset),
        )
        : [];

    return (
        <Card
            size="small"
            title={
                <Space>
                    <CloudSyncOutlined />
                    <span>数据更新检查</span>
                    {diff && (
                        <Text type="secondary" className="text-xs">
                            （检查时间: {new Date(diff.timestamp).toLocaleTimeString()}）
                        </Text>
                    )}
                </Space>
            }
            extra={
                <Space>
                    <Button
                        icon={loading ? <SyncOutlined spin /> : <CloudSyncOutlined />}
                        onClick={onCheckUpdates}
                        loading={loading}
                        size="small"
                    >
                        {diff ? '重新检查' : '检查更新'}
                    </Button>
                    {syncableDatasets.length > 0 && (
                        <Button
                            type="primary"
                            size="small"
                            onClick={() => onSyncSelected(syncableDatasets.map(d => d.dataset))}
                        >
                            同步 {syncableDatasets.length} 个数据集
                        </Button>
                    )}
                </Space>
            }
        >
            {diff ? (
                <div>
                    <Space size="large" className="mb-3">
                        <Statistic
                            title="已最新"
                            value={summary.up_to_date}
                            valueStyle={{ color: '#10b981', fontSize: 20 }}
                            prefix={<CheckCircleFilled />}
                        />
                        <Statistic
                            title="有更新"
                            value={summary.updates_available}
                            valueStyle={{ color: '#f59e0b', fontSize: 20 }}
                            prefix={<ExclamationCircleFilled />}
                        />
                        <Statistic
                            title="未同步"
                            value={summary.not_synced}
                            valueStyle={{ color: '#94a3b8', fontSize: 20 }}
                            prefix={<QuestionCircleFilled />}
                        />
                        <Statistic
                            title="未知"
                            value={summary.unknown}
                            valueStyle={{ color: '#cbd5e1', fontSize: 20 }}
                        />
                    </Space>

                    {syncableDatasets.length > 0 && (
                        <div className="mt-2">
                            <Text type="secondary" className="text-xs">可同步的数据集：</Text>
                            <div className="mt-1 flex flex-wrap gap-1">
                                {syncableDatasets.map(d => {
                                    const cfg = STATUS_CONFIG[d.status];
                                    return (
                                        <Tooltip
                                            key={d.dataset}
                                            title={
                                                <div className="text-xs">
                                                    <div>{d.name}</div>
                                                    {d.local.end_date && (
                                                        <div>本地: {formatRemoteDate(d.local.end_date)}</div>
                                                    )}
                                                    {d.remote?.end_date && (
                                                        <div>远端: {formatRemoteDate(d.remote.end_date)}</div>
                                                    )}
                                                    {d.new_files > 0 && (
                                                        <div>约 {d.new_files} 个新文件</div>
                                                    )}
                                                </div>
                                            }
                                        >
                                            <Tag color={cfg.color === '#10b981' ? 'green' : cfg.color === '#f59e0b' ? 'orange' : 'default'}>
                                                {d.name}
                                            </Tag>
                                        </Tooltip>
                                    );
                                })}
                            </div>
                        </div>
                    )}

                    {summary.up_to_date === summary.total_datasets && (
                        <Text type="success" className="text-sm">
                            {visibleDatasetNames
                                ? '下方列表中的数据集均为最新，无需同步'
                                : '所有数据集均为最新，无需同步'}
                        </Text>
                    )}
                    {hiddenSyncable.length > 0 && (
                        <div className="mt-1">
                            <Text type="secondary" className="text-xs">
                                另有 {hiddenSyncable.length} 个隐藏数据集
                                （{hiddenSyncable.map(d => d.name).join('、')}）需要同步，
                                未在下方列表展示，可单独按需同步
                            </Text>
                        </div>
                    )}
                </div>
            ) : (
                <Text type="secondary" className="text-sm">
                    点击「检查更新」对比远端与本地数据差异，仅查询元数据不消耗流量
                </Text>
            )}
        </Card>
    );
};

export default QuantDBDiffSummary;
