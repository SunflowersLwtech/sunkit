import React, {useMemo} from 'react';
import {AbsoluteFill, interpolate, spring} from 'remotion';
import type {AgentVisualProps} from '../AgentVisualTypes';

type PremiumScene = {
  id?: string;
  scene_type?: string;
  title?: string;
  objective?: string;
  teaching_beats?: string[];
  object_refs?: string[];
  motion_beats?: string[];
};

type TopicObject = {
  id?: string;
  kind?: string;
  label?: string;
  detail?: string;
  source_ref?: string;
};

type PremiumSpec = {
  profile?: {
    orientation?: 'vertical' | 'horizontal';
    aspect_ratio?: '9:16' | '16:9';
    style_family?: string;
    motion_comfort?: string;
    safe_space_px?: number;
  };
  knowledge_arc?: Record<string, string>;
  topic_objects?: TopicObject[];
  visual_scenes?: PremiumScene[];
  motion_beats?: {type?: string; target?: string; intensity?: string}[];
};

const palette = {
  ink: '#08111d',
  night: '#122236',
  slate: '#223246',
  ivory: '#fffaf0',
  paper: '#f7f3ea',
  mist: '#edf5ff',
  cyan: '#6ee7ff',
  amber: '#ffd166',
  green: '#9cf6c3',
  coral: '#ff8b66',
  blue: '#89a9ff',
  plum: '#c7a6ff',
  dark: '#122033',
};

const tones = [palette.cyan, palette.amber, palette.green, palette.coral, palette.blue, palette.plum];

const clamp = (value: number, min = 0, max = 1) => Math.max(min, Math.min(max, value));

const clean = (value: unknown, limit = 96): string => {
  const text = String(value ?? '').replace(/\s+/g, ' ').trim();
  if (!text) {
    return '';
  }
  return text.length > limit ? `${text.slice(0, limit - 1).trim()}...` : text;
};

const pct = (value: number) => `${Math.round(clamp(value) * 100)}%`;

const soft = (value: number, floor = 0.72) => floor + clamp(value) * (1 - floor);

const sceneLabel = (sceneType: string, title?: string) => {
  const raw = clean(title || '', 32);
  if (raw && !/hero|problem|mechanism|architecture|repo|file|terminal|comparison|matrix|takeaway/i.test(raw)) {
    return raw;
  }
  if (/hero/i.test(sceneType)) {
    return '问题入口';
  }
  if (/mechanism/i.test(sceneType)) {
    return '机制拆解';
  }
  if (/repo|terminal|code/i.test(sceneType)) {
    return '源码证据';
  }
  if (/architecture/i.test(sceneType)) {
    return '架构位置';
  }
  if (/metric|timeline/i.test(sceneType)) {
    return '权衡坐标';
  }
  if (/decision/i.test(sceneType)) {
    return '适用边界';
  }
  return '判断框架';
};

const objectKind = (kind: string) => {
  if (/repo|file|code/i.test(kind)) {
    return '源码入口';
  }
  if (/api|surface|route/i.test(kind)) {
    return '接口层';
  }
  if (/metric|score|benchmark/i.test(kind)) {
    return '指标';
  }
  if (/failure|boundary|risk/i.test(kind)) {
    return '失败边界';
  }
  if (/decision|judgment/i.test(kind)) {
    return '判断框架';
  }
  return '架构节点';
};

const useShowcaseModel = (props: AgentVisualProps, spec?: PremiumSpec, visualScenes?: PremiumScene[]) => {
  const {data} = props;
  return useMemo(() => {
    const arc = spec?.knowledge_arc ?? {};
    const fallbackTitle = clean(data.displayTitle || data.title || '机制拆解主题', 86);
    const fallbackObjects = [
      {id: 'obj_problem', kind: 'architecture_node', label: fallbackTitle, detail: clean(data.metricLine || '机制解释', 80)},
      {id: 'obj_fit', kind: 'decision_axis', label: clean(data.audienceMetricLine || '适用场景', 48), detail: '实际适用与失败边界'},
      {id: 'obj_takeaway', kind: 'judgment_framework', label: clean(data.source || '证据来源', 48), detail: '判断框架'},
    ];
    const objects = (Array.isArray(spec?.topic_objects) && spec.topic_objects.length >= 3 ? spec.topic_objects : fallbackObjects)
      .slice(0, 9)
      .map((item, index) => ({
        id: clean(item.id || `obj_${index + 1}`, 28),
        kind: clean(item.kind || 'architecture_node', 34),
        label: clean(item.label || fallbackObjects[index % fallbackObjects.length].label, 56),
        detail: clean(item.detail || fallbackObjects[index % fallbackObjects.length].detail, 94),
        tone: tones[index % tones.length],
      }));
    const defaultScenes: PremiumScene[] = [
      {scene_type: 'HeroProblemScene', title: fallbackTitle, objective: clean(arc.hook || data.metricLine || '先界定问题', 110)},
      {scene_type: 'MechanismExplodedView', title: '机制拆解', objective: clean(arc.mechanism || '解释系统怎么运作', 110)},
      {scene_type: 'ArchitectureFlowScene', title: '架构位置', objective: clean(arc.architecture_position || '放进工作流里看位置', 110)},
      {scene_type: 'CodeOrTerminalScene', title: '工作流入口', objective: clean(arc.practical_fit || '把真实用法落到步骤', 110)},
      {scene_type: 'DecisionMatrixScene', title: '边界判断', objective: clean(arc.failure_boundary || '说明什么时候会失效', 110)},
      {scene_type: 'KnowledgeTakeawayScene', title: '判断框架', objective: clean(arc.judgment_framework || data.cta || '留下可复用框架', 110)},
    ];
    const rawScenes = Array.isArray(visualScenes) && visualScenes.length > 0
      ? visualScenes
      : Array.isArray(spec?.visual_scenes)
        ? spec.visual_scenes
        : [];
    const scenes = (rawScenes.length >= 5 ? rawScenes : defaultScenes).slice(0, 9).map((scene, index) => ({
      id: clean(scene.id || `scene_${index + 1}`, 28),
      scene_type: clean(scene.scene_type || defaultScenes[index % defaultScenes.length].scene_type, 42),
      title: sceneLabel(scene.scene_type || '', scene.title || defaultScenes[index % defaultScenes.length].title),
      objective: clean(scene.objective || defaultScenes[index % defaultScenes.length].objective, 128),
      teaching_beats: (scene.teaching_beats ?? []).slice(0, 4).map((item) => clean(item, 44)).filter(Boolean),
      object_refs: scene.object_refs ?? [],
      motion_beats: scene.motion_beats ?? ['reveal', 'object_focus', 'dwell'],
      tone: tones[index % tones.length],
    }));
    return {
      title: fallbackTitle,
      source: clean(data.source || 'source backed', 46),
      metric: clean(data.metricLine || data.audienceMetricLine || arc.practical_fit || 'source-bounded judgment', 72),
      arc,
      objects,
      scenes,
    };
  }, [data, spec, visualScenes]);
};

type ShowcaseModel = ReturnType<typeof useShowcaseModel>;
type ShowcaseScene = ShowcaseModel['scenes'][number];

const topicText = (model: ShowcaseModel) =>
  `${model.title} ${Object.values(model.arc).join(' ')} ${model.objects.map((item) => `${item.label} ${item.detail}`).join(' ')}`;

const isSearchTopic = (model: ShowcaseModel) => /google search|ai mode|search agents|search box|search\b|搜索|查询|检索|rag|索引|fan-out|query fan/i.test(topicText(model));

const isRepoTopic = (model: ShowcaseModel) => {
  const text = topicText(model);
  const hasRepoScene = model.scenes.some((scene) => /RepoFileTreeReveal/i.test(scene.scene_type));
  const hasRepoObject = model.objects.some((object) => /repo_file|api_surface|source|module|package|readme/i.test(object.kind));
  return hasRepoScene || hasRepoObject || /github|repository|repo\b|readme|package\.json|pyproject|src\/|cli\b|sdk\b|源码/i.test(text);
};

const repoFilesFor = (model: ShowcaseModel) => {
  const sourceObjects = model.objects.filter((object) => /repo|file|api|source|module|code/i.test(object.kind));
  const workflowObjects = [
    coreObjectFor(model),
    guardObjectFor(model),
    metricObjectFor(model),
    model.objects[3] ?? model.objects[0],
    model.objects[4] ?? model.objects[1] ?? model.objects[0],
  ].filter(Boolean).map((object, index) => ({
    id: object.id || `workflow_${index + 1}`,
    kind: object.kind || 'workflow_node',
    label: object.label || ['任务入口', '循环控制', '验收边界', '输出指标', '判断框架'][index],
    detail: object.detail || [model.arc.hook, model.arc.mechanism, model.arc.failure_boundary, model.arc.practical_fit, model.arc.judgment_framework][index] || '工作流节点',
    tone: object.tone || tones[index % tones.length],
  }));
  const fallback = workflowObjects.length >= 3 ? workflowObjects : [
    {id: 'workflow_input', kind: 'workflow_node', label: '任务入口', detail: model.arc.hook || '问题进入流程', tone: palette.cyan},
    {id: 'workflow_core', kind: 'workflow_node', label: '循环控制', detail: model.arc.mechanism || '核心机制', tone: palette.amber},
    {id: 'workflow_gate', kind: 'workflow_node', label: '验收边界', detail: model.arc.failure_boundary || '失败边界', tone: palette.coral},
    {id: 'workflow_output', kind: 'workflow_node', label: '输出指标', detail: model.arc.practical_fit || '可判断结果', tone: palette.green},
  ];
  return (sourceObjects.length >= 3 ? sourceObjects : fallback).slice(0, 5);
};

const repoLanesFor = (model: ShowcaseModel) => [
  ['入口', repoFilesFor(model)[0]?.label || 'README', model.arc.hook || model.title, palette.cyan],
  ['机制', repoFilesFor(model)[1]?.label || 'core module', model.arc.mechanism || '把输入转成可解释输出', palette.amber],
  ['运行', repoFilesFor(model)[2]?.label || 'API / CLI', model.arc.practical_fit || '接入真实工作流', palette.green],
  ['边界', repoFilesFor(model)[3]?.label || 'tests / evals', model.arc.failure_boundary || '暴露失败成本', palette.coral],
];

const pickObject = (model: ShowcaseModel, matcher: RegExp, fallbackIndex: number) =>
  model.objects.find((object) => matcher.test(`${object.kind} ${object.label} ${object.detail}`)) ??
  model.objects[fallbackIndex] ??
  model.objects[0];

const coreObjectFor = (model: ShowcaseModel) => pickObject(model, /architecture|node|mechanism|loop|control|循环|控制/i, 0);
const guardObjectFor = (model: ShowcaseModel) => pickObject(model, /failure|boundary|risk|guard|gate|验收|边界|失败|标准/i, 1);
const metricObjectFor = (model: ShowcaseModel) => pickObject(model, /metric|score|benchmark|throughput|pr|指标|吞吐/i, 2);

const workflowLabel = (value: unknown, fallback: string, limit = 18) => clean(value || fallback, limit) || fallback;

const coreLabelFor = (model: ShowcaseModel, limit = 18) => workflowLabel(coreObjectFor(model)?.label, '核心机制', limit);
const guardLabelFor = (model: ShowcaseModel, limit = 18) => workflowLabel(guardObjectFor(model)?.label, '验收边界', limit);
const metricLabelFor = (model: ShowcaseModel, limit = 18) => workflowLabel(metricObjectFor(model)?.label, '输出指标', limit);

const horizontalHeadlineSize = (text: string, large: number, medium: number, small: number) => {
  const length = Array.from(text).length;
  if (length >= 62) {
    return small;
  }
  if (length >= 44) {
    return medium;
  }
  return large;
};

const workflowActionsFor = (model: ShowcaseModel) => {
  const core = coreLabelFor(model, 10);
  const guard = guardLabelFor(model, 10);
  return [
    ['input', '任务进入', palette.cyan],
    ['loop', core, palette.amber],
    ['gate', guard, palette.coral],
  ];
};

const workflowNodesFor = (model: ShowcaseModel, scene: ShowcaseScene) => {
  const core = coreObjectFor(model);
  const guard = guardObjectFor(model);
  const metric = metricObjectFor(model);
  return [
    ['任务入口', clean(model.arc.hook || model.title, 60), palette.cyan],
    [coreLabelFor(model, 18), clean(model.arc.mechanism || core?.detail || '把输入变成可检查流程', 66), scene.tone],
    [guardLabelFor(model, 18), clean(model.arc.failure_boundary || guard?.detail || '把隐性标准显性化', 66), palette.coral],
    [metricLabelFor(model, 18), clean(model.arc.practical_fit || metric?.detail || model.arc.takeaway || '输出可判断结果', 66), palette.amber],
  ];
};

const CinematicBackdrop: React.FC<{frame: number; width: number; height: number; activeScene: ShowcaseScene; progress: number}> = ({
  frame,
  width,
  height,
  activeScene,
  progress,
}) => {
  const isHorizontal = width > height;
  const activeTone = activeScene.tone;
  const sceneType = activeScene.scene_type;
  const pan = interpolate(Math.sin(frame / 160), [-1, 1], [-34, 34]);
  const sweep = interpolate((frame % 210) / 210, [0, 1], [-0.18, 1.18]);
  const stagePulse = interpolate(Math.sin(frame / 96), [-1, 1], [0.86, 1.08]);
  const isDecision = /decision|takeaway|metric/i.test(sceneType);
  const isSystem = /repo|mechanism|architecture|code/i.test(sceneType);
  const stageGradient = isDecision
    ? `linear-gradient(122deg, #0d1118 0%, #1c2532 36%, #574b39 86%, #f0dfbc 170%)`
    : isSystem
      ? `linear-gradient(118deg, #050b13 0%, #132840 40%, #203956 72%, #d9f6ff 170%)`
      : `linear-gradient(118deg, #070b12 0%, #172335 42%, #273142 70%, #fff2d2 168%)`;
  return (
    <AbsoluteFill style={{background: palette.ink, overflow: 'hidden'}}>
      <div
        style={{
          position: 'absolute',
          inset: 0,
          background: stageGradient,
        }}
      />
      <div
        style={{
          position: 'absolute',
          left: isHorizontal ? width * 0.48 : width * 0.16,
          top: isHorizontal ? -height * 0.24 : height * 0.08,
          width: isHorizontal ? width * 0.72 : width * 1.2,
          height: isHorizontal ? height * 1.16 : height * 0.62,
          borderRadius: '50%',
          background: `radial-gradient(circle at 48% 48%, ${activeTone}4d 0%, ${activeTone}1f 34%, transparent 68%)`,
          filter: 'blur(8px)',
          transform: `translateX(${pan * 0.45}px) scale(${stagePulse})`,
          opacity: 0.84,
        }}
      />
      <svg
        width={width}
        height={height}
        viewBox={`0 0 ${width} ${height}`}
        style={{position: 'absolute', inset: 0, opacity: isSystem ? 0.32 : 0.22}}
      >
        <defs>
          <linearGradient id="stageMesh" x1="0" x2="1" y1="0" y2="1">
            <stop offset="0%" stopColor={palette.cyan} stopOpacity="0.12" />
            <stop offset="42%" stopColor={activeTone} stopOpacity="0.22" />
            <stop offset="100%" stopColor={palette.amber} stopOpacity="0.10" />
          </linearGradient>
          <linearGradient id="stageSweep" x1="0" x2="1" y1="0" y2="0">
            <stop offset="0%" stopColor="transparent" />
            <stop offset="50%" stopColor={activeTone} stopOpacity="0.56" />
            <stop offset="100%" stopColor="transparent" />
          </linearGradient>
        </defs>
        {Array.from({length: isHorizontal ? 9 : 12}).map((_, index) => {
          const y = (height / (isHorizontal ? 10 : 14)) * index;
          const bend = Math.sin(index * 0.82) * 10;
          return (
            <path
              key={`h-${index}`}
              d={`M -80 ${y + bend} C ${width * 0.23} ${y - 44} ${width * 0.68} ${y + 64} ${width + 90} ${y + bend * 0.4}`}
              stroke="url(#stageMesh)"
              strokeWidth="1.2"
              fill="none"
            />
          );
        })}
        {Array.from({length: isHorizontal ? 10 : 8}).map((_, index) => {
          const x = (width / (isHorizontal ? 12 : 8)) * index;
          const bend = Math.cos(index * 0.74) * 9;
          return (
            <path
              key={`v-${index}`}
              d={`M ${x + bend} -80 C ${x - 72} ${height * 0.27} ${x + 88} ${height * 0.66} ${x + bend * 0.5} ${height + 90}`}
              stroke="url(#stageMesh)"
              strokeWidth="1.1"
              fill="none"
            />
          );
        })}
        <rect
          x={width * sweep - width * 0.28}
          y="0"
          width={width * 0.26}
          height={height}
          fill="url(#stageSweep)"
          opacity="0.22"
          transform={`skewX(${isHorizontal ? -10 : -7})`}
        />
      </svg>
      <div
        style={{
          position: 'absolute',
          left: -120,
          right: -120,
          bottom: -110,
          height: isHorizontal ? 260 : 420,
          background: `linear-gradient(180deg, transparent, rgba(8,17,29,0.62) 34%, rgba(8,17,29,0.96) 100%)`,
        }}
      />
      {!isHorizontal ? (
        <div
          style={{
            position: 'absolute',
            left: 52,
            right: 52,
            bottom: 62,
            height: 5,
            borderRadius: 99,
            background: 'rgba(255,250,240,0.12)',
            overflow: 'hidden',
          }}
        >
          <div style={{height: '100%', width: pct(progress), background: `linear-gradient(90deg, ${palette.cyan}, ${activeTone}, ${palette.amber})`}} />
        </div>
      ) : null}
    </AbsoluteFill>
  );
};

const StageTitle: React.FC<{model: ShowcaseModel; activeScene: ShowcaseScene; frame: number; width: number; height: number}> = ({
  model,
  activeScene,
  frame,
  width,
  height,
}) => {
  const isHorizontal = width > height;
  const enter = spring({frame, fps: 30, config: {damping: 24, stiffness: 90}});
  return (
    <div
      style={{
        position: 'absolute',
        top: isHorizontal ? 34 : 34,
        left: isHorizontal ? 72 : 58,
        right: isHorizontal ? 72 : 58,
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        opacity: enter,
      }}
    >
      <div style={{display: 'flex', gap: 10, alignItems: 'center', minWidth: 0}}>
        <div
          style={{
            width: 10,
            height: 10,
            borderRadius: 99,
            background: activeScene.tone,
            boxShadow: `0 0 28px ${activeScene.tone}`,
          }}
        />
      </div>
      {isHorizontal ? (
        <div style={{display: 'grid', gap: 10, justifyItems: 'stretch', width: 420}}>
          <div style={{display: 'grid', gridTemplateColumns: `repeat(${model.scenes.length}, 1fr)`, gap: 7}}>
            {model.scenes.map((scene) => (
              <div key={scene.id} style={{height: 6, borderRadius: 99, background: scene.id === activeScene.id ? scene.tone : 'rgba(255,250,240,0.14)'}} />
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
};

const TeachingBeatStrip: React.FC<{scene: ShowcaseScene; frame: number; fps: number; width: number; height: number}> = ({
  scene,
  frame,
  fps,
  width,
  height,
}) => {
  const isHorizontal = width > height;
  const beats = scene.teaching_beats.length > 0 ? scene.teaching_beats : ['机制', '架构位置', '失败边界'];
  if (!isHorizontal) {
    return null;
  }
  return (
    <div
      style={{
        position: 'absolute',
        right: 72,
        top: 136,
        width: 560,
        display: 'grid',
        gridTemplateColumns: `repeat(${beats.length}, 1fr)`,
        gap: 10,
      }}
    >
      {beats.map((beat, index) => {
        const enter = spring({frame: frame - index * 6, fps, config: {damping: 22, stiffness: 110}});
        return (
          <div
            key={`${beat}-${index}`}
            style={{
              minHeight: 54,
              borderTop: `2px solid ${index === 0 ? scene.tone : 'rgba(255,250,240,0.22)'}`,
              paddingTop: 10,
              color: index === 0 ? palette.ivory : palette.mist,
              fontSize: 15,
              lineHeight: 1.14,
              fontWeight: 850,
              opacity: soft(enter, 0.68),
              overflowWrap: 'anywhere',
            }}
          >
            {beat}
          </div>
        );
      })}
    </div>
  );
};

const ObjectChip: React.FC<{
  object: ShowcaseModel['objects'][number];
  index: number;
  localFrame: number;
  fps: number;
  active?: boolean;
}> = ({object, index, localFrame, fps, active}) => {
  const enter = spring({frame: localFrame - index * 8, fps, config: {damping: 21, stiffness: 120}});
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: '74px 1fr',
        gap: 16,
        alignItems: 'center',
        padding: '16px 18px',
        borderRadius: 22,
        background: active ? object.tone : 'rgba(255,250,240,0.08)',
        border: `1px solid ${active ? object.tone : 'rgba(255,250,240,0.15)'}`,
        boxShadow: active ? `0 26px 70px ${object.tone}2c` : '0 14px 42px rgba(0,0,0,0.16)',
        opacity: soft(enter, 0.74),
        transform: `translateY(${(1 - enter) * 16}px)`,
        minHeight: 92,
      }}
    >
      <div
        style={{
          height: 58,
          borderRadius: 17,
          display: 'grid',
          placeItems: 'center',
          textAlign: 'center',
          padding: '0 8px',
          background: active ? 'rgba(18,32,51,0.15)' : `${object.tone}35`,
          color: active ? palette.dark : palette.ivory,
          fontSize: 12,
          lineHeight: 1.08,
          fontWeight: 950,
          overflow: 'hidden',
        }}
      >
        {objectKind(object.kind)}
      </div>
      <div style={{minWidth: 0}}>
        <div style={{fontSize: 21, lineHeight: 1.06, color: active ? palette.dark : palette.ivory, fontWeight: 950, overflowWrap: 'anywhere'}}>
          {object.label}
        </div>
        <div style={{marginTop: 8, fontSize: 15, lineHeight: 1.18, color: active ? '#31465a' : palette.mist, fontWeight: 680}}>
          {object.detail}
        </div>
      </div>
    </div>
  );
};

const SearchPipelineDiagram: React.FC<{
  model: ShowcaseModel;
  scene: ShowcaseScene;
  frame: number;
  localFrame: number;
  fps: number;
  compact?: boolean;
}> = ({model, scene, frame, localFrame, fps, compact}) => {
  const fanout = interpolate(localFrame, [12, 92], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  const retrieve = interpolate(localFrame, [84, 168], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  const synth = interpolate(localFrame, [150, 230], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  const queries = ['实体补全', '来源过滤', '意图拆分'];
  const docs = ['网页索引', '新闻源', '官方博客', '历史上下文', '图片线索', '结构化事实'];
  const height = compact ? 710 : 620;
  return (
    <div
      style={{
        position: 'relative',
        height,
        minHeight: 0,
        borderRadius: compact ? 0 : 30,
        overflow: 'hidden',
        background: compact ? 'transparent' : 'linear-gradient(140deg, rgba(255,250,240,0.11), rgba(8,17,29,0.78))',
        border: compact ? 'none' : `1px solid ${scene.tone}55`,
        boxShadow: compact ? 'none' : `0 34px 98px rgba(0,0,0,0.30), 0 0 86px ${scene.tone}18`,
      }}
    >
      <svg width="100%" height="100%" viewBox="0 0 760 620" style={{position: 'absolute', inset: 0}}>
        <defs>
          <linearGradient id="queryFanout" x1="0" x2="1">
            <stop offset="0%" stopColor={palette.cyan} />
            <stop offset="50%" stopColor={scene.tone} />
            <stop offset="100%" stopColor={palette.amber} />
          </linearGradient>
          <linearGradient id="ragPull" x1="0" x2="1">
            <stop offset="0%" stopColor={palette.green} />
            <stop offset="100%" stopColor={palette.ivory} />
          </linearGradient>
        </defs>
        {[0, 1, 2].map((index) => {
          const y = 142 + index * 86;
          return (
            <path
              key={`fan-${index}`}
              d={`M118 86 C220 ${y - 46} 272 ${y + 18} 356 ${y}`}
              fill="none"
              stroke="url(#queryFanout)"
              strokeWidth="5"
              strokeLinecap="round"
              strokeDasharray="520"
              strokeDashoffset={520 * (1 - fanout)}
              opacity={0.72 + index * 0.08}
            />
          );
        })}
        {[0, 1, 2].map((index) => {
          const y = 158 + index * 96;
          return (
            <path
              key={`pull-${index}`}
              d={`M512 ${y} C592 ${y - 28} 628 300 684 430`}
              fill="none"
              stroke="url(#ragPull)"
              strokeWidth="4"
              strokeLinecap="round"
              strokeDasharray="520"
              strokeDashoffset={520 * (1 - retrieve)}
              opacity="0.74"
            />
          );
        })}
      </svg>
      <div style={{position: 'absolute', left: 34, top: 34, width: compact ? 210 : 245, padding: '18px 20px', borderRadius: 24, background: compact ? `linear-gradient(135deg, ${palette.cyan}, ${palette.paper})` : palette.paper, color: palette.dark, boxShadow: '0 24px 70px rgba(0,0,0,0.24)'}}>
        <div style={{fontSize: 14, fontWeight: 950, color: '#4d657a'}}>用户问题</div>
        <div style={{marginTop: 12, fontSize: 27, lineHeight: 1.05, fontWeight: 970}}>
          {clean(model.arc.hook || model.title, compact ? 28 : 46)}
        </div>
      </div>
      <div style={{position: 'absolute', left: compact ? 286 : 332, top: compact ? 116 : 108, display: 'grid', gap: 18}}>
        {queries.map((label, index) => {
          const enter = spring({frame: localFrame - 22 - index * 10, fps, config: {damping: 21, stiffness: 118}});
          return (
            <div
              key={label}
              style={{
                width: compact ? 206 : 190,
                minHeight: compact ? 74 : 64,
                borderRadius: 20,
                padding: '12px 16px',
                background: index === 1 ? scene.tone : 'rgba(255,250,240,0.10)',
                border: `1px solid ${index === 1 ? scene.tone : 'rgba(255,250,240,0.16)'}`,
                color: index === 1 ? palette.dark : palette.ivory,
                opacity: soft(enter, 0.66),
                transform: `translateX(${(1 - enter) * 18}px)`,
              }}
            >
              <div style={{fontSize: 20, fontWeight: 960}}>Query Fan-out</div>
              <div style={{marginTop: 6, fontSize: 15, fontWeight: 760}}>{label}</div>
            </div>
          );
        })}
      </div>
      <div style={{position: 'absolute', right: compact ? 8 : 36, top: compact ? 78 : 82, width: compact ? 190 : 176, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10}}>
        {docs.map((doc, index) => {
          const hot = retrieve * docs.length > index;
          const lift = Math.sin(frame / 62 + index) * 3;
          return (
            <div
              key={doc}
              style={{
                height: 70,
                borderRadius: 16,
                padding: '9px 10px',
                background: hot ? palette.green : 'rgba(255,250,240,0.09)',
                color: hot ? palette.dark : palette.mist,
                border: `1px solid ${hot ? palette.green : 'rgba(255,250,240,0.15)'}`,
                fontSize: 13,
                lineHeight: 1.08,
                fontWeight: 900,
                transform: `translateY(${lift}px)`,
                boxShadow: hot ? `0 16px 42px ${palette.green}26` : 'none',
              }}
            >
              {doc}
            </div>
          );
        })}
      </div>
      <div
        style={{
          position: 'absolute',
          left: compact ? 18 : 74,
          right: compact ? 18 : 58,
          bottom: compact ? 20 : 42,
          minHeight: compact ? 142 : 122,
          borderRadius: 26,
          padding: '20px 24px',
          background: synth > 0.78 ? `linear-gradient(90deg, ${scene.tone}, ${palette.ivory})` : 'rgba(255,250,240,0.10)',
          border: `1px solid ${scene.tone}`,
          color: synth > 0.78 ? palette.dark : palette.ivory,
          boxShadow: `0 28px 80px rgba(0,0,0,0.26), 0 0 72px ${scene.tone}22`,
          opacity: soft(synth, 0.64),
        }}
      >
        <div style={{fontSize: 15, fontWeight: 980}}>RAG 合成</div>
        <div style={{marginTop: 10, fontSize: compact ? 24 : 28, lineHeight: 1.08, fontWeight: 960}}>
          {clean(model.arc.architecture_position || '索引证据被拉回，再压缩成可追溯答案。', compact ? 54 : 68)}
        </div>
      </div>
    </div>
  );
};

const RepoSystemDiagram: React.FC<{
  model: ShowcaseModel;
  scene: ShowcaseScene;
  frame: number;
  localFrame: number;
  fps: number;
  compact?: boolean;
}> = ({model, scene, frame, localFrame, fps, compact}) => {
  const build = interpolate(localFrame, [16, 148], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  const recall = interpolate(localFrame, [94, 214], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  const height = compact ? 710 : 620;
  const coreFocus = spring({frame: localFrame - 36, fps, config: {damping: 26, stiffness: 92}});
  const files = repoFilesFor(model);
  const nodes = workflowNodesFor(model, scene);
  const actions = workflowActionsFor(model);
  const coreLabel = coreLabelFor(model, compact ? 12 : 14);
  const positions = compact
    ? [
      [24, 524],
      [266, 182],
      [322, 402],
      [376, 136],
    ]
    : [
      [38, 470],
      [268, 74],
      [476, 438],
      [640, 186],
    ];
  const particles = Array.from({length: compact ? 7 : 11}).map((_, index) => {
    const t = (frame / 74 + index / (compact ? 7 : 11)) % 1;
    const x = compact
      ? 76 + t * 458
      : 88 + t * 650;
    const y = compact
      ? 118 + Math.sin(t * Math.PI * 2.1) * 156 + t * 330
      : 304 + Math.sin(t * Math.PI * 2.25) * 126 - t * 72;
    return {x, y, opacity: 0.22 + 0.52 * (1 - Math.abs(t - 0.5) * 1.6), scale: 0.72 + t * 0.52};
  });
  return (
    <div
      style={{
        position: 'relative',
        height,
        minHeight: 0,
        borderRadius: 0,
        overflow: 'visible',
        background: 'transparent',
        border: 'none',
        boxShadow: 'none',
      }}
    >
      <svg width="100%" height="100%" viewBox="0 0 840 620" style={{position: 'absolute', inset: 0}}>
        <defs>
          <linearGradient id="memoryTrace" x1="0" x2="1">
            <stop offset="0%" stopColor={palette.cyan} />
            <stop offset="40%" stopColor={scene.tone} />
            <stop offset="76%" stopColor={palette.green} />
            <stop offset="100%" stopColor={palette.amber} />
          </linearGradient>
          <radialGradient id="memoryCoreGlow" cx="50%" cy="50%" r="54%">
            <stop offset="0%" stopColor={scene.tone} stopOpacity="0.54" />
            <stop offset="46%" stopColor={palette.green} stopOpacity="0.18" />
            <stop offset="100%" stopColor="transparent" stopOpacity="0" />
          </radialGradient>
        </defs>
        <ellipse cx="408" cy="272" rx="230" ry="164" fill="url(#memoryCoreGlow)" opacity="0.82" />
        <path d="M84 304 C178 122 296 148 386 240 C510 366 608 376 750 206" fill="none" stroke="rgba(255,250,240,0.09)" strokeWidth="30" strokeLinecap="round" />
        <path d="M84 304 C178 122 296 148 386 240 C510 366 608 376 750 206" fill="none" stroke="url(#memoryTrace)" strokeWidth="8" strokeLinecap="round" strokeDasharray="1120" strokeDashoffset={1120 * (1 - build)} />
        <path d="M478 356 C388 452 260 432 154 342" fill="none" stroke={palette.green} strokeWidth="5" strokeLinecap="round" strokeDasharray="560" strokeDashoffset={560 * (1 - recall)} opacity="0.82" />
        <path d="M238 94 L536 94 L646 210 L332 210 Z" fill={`${palette.ivory}0d`} stroke={`${scene.tone}72`} strokeWidth="2" />
        <path d="M254 126 L560 126 L632 204 L324 204 Z" fill={`${scene.tone}16`} stroke={`${scene.tone}62`} strokeWidth="2" />
        <path d="M260 476 L610 476 L700 554 L352 554 Z" fill={`${palette.green}10`} stroke={`${palette.green}5f`} strokeWidth="2" />
        <text x="440" y="154" fill={scene.tone} fontSize="18" fontWeight="900" opacity="0.9">{actions[1][1]}</text>
        <text x="512" y="428" fill={palette.green} fontSize="18" fontWeight="900" opacity="0.9">{actions[2][1]}</text>
        <text x="704" y="174" fill={palette.amber} fontSize="18" fontWeight="900" opacity="0.9">输出</text>
      </svg>
      <div
        style={{
          position: 'absolute',
          left: compact ? 154 : 266,
          top: compact ? 166 : 142,
          width: compact ? 300 : 350,
          height: compact ? 236 : 260,
          color: palette.ivory,
          textShadow: '0 16px 70px rgba(0,0,0,0.52)',
          transform: `perspective(1200px) rotateX(${compact ? 34 : 38}deg) rotateZ(${compact ? -7 : -9}deg) translateY(${(1 - coreFocus) * 20 + Math.sin(frame / 94) * 3}px) scale(${0.94 + coreFocus * 0.06})`,
          transformOrigin: 'center',
          opacity: soft(coreFocus, 0.72),
        }}
      >
        <div style={{position: 'absolute', left: 28, top: 26, width: 118, height: 3, background: scene.tone, boxShadow: `0 0 26px ${scene.tone}`}} />
        <div style={{position: 'absolute', left: 30, top: 42, fontSize: 13, fontWeight: 980, color: scene.tone}}>CONTROL CORE</div>
        <div style={{position: 'absolute', left: 30, right: 30, top: compact ? 78 : 82, fontSize: compact ? 58 : 72, lineHeight: 0.86, fontWeight: 990}}>
          {coreLabel}
        </div>
        <div style={{position: 'absolute', left: 30, right: 34, bottom: 30, fontSize: compact ? 18 : 20, lineHeight: 1.08, fontWeight: 850, color: palette.mist}}>
          {clean(model.arc.mechanism || nodes[1][1], compact ? 58 : 74)}
        </div>
        {[0, 1, 2].map((index) => (
          <div
            key={`core-slab-${index}`}
            style={{
              position: 'absolute',
              left: 24 + index * 18,
              right: 40 - index * 4,
              top: 124 + index * 34,
              height: 14,
              borderRadius: 999,
              background: index === 0 ? `${scene.tone}66` : `rgba(255,250,240,${0.13 - index * 0.02})`,
              opacity: 0.58,
              boxShadow: index === 0 ? `0 0 26px ${scene.tone}28` : 'none',
            }}
          />
        ))}
      </div>
      <div
        style={{
          position: 'absolute',
          left: compact ? 28 : 40,
          top: compact ? 32 : 56,
          width: compact ? 184 : 220,
          display: 'grid',
          gap: compact ? 10 : 12,
        }}
      >
        {files.slice(0, compact ? 3 : 4).map((file, index) => {
          const enter = spring({frame: localFrame - 8 - index * 7, fps, config: {damping: 20, stiffness: 118}});
          return (
          <div
            key={`file-rail-${file.label}-${index}`}
              style={{
                display: 'grid',
                gridTemplateColumns: compact ? '22px 1fr' : '28px 1fr',
                gap: 10,
                alignItems: 'center',
                opacity: soft(enter, 0.58),
                transform: `translateX(${(1 - enter) * -16}px)`,
              }}
            >
              <div style={{height: 2, background: file.tone, boxShadow: `0 0 18px ${file.tone}`}} />
              <div>
                <div style={{fontFamily: 'SFMono-Regular, Menlo, Consolas, monospace', fontSize: compact ? 18 : 20, color: palette.ivory, fontWeight: 900}}>
                  {clean(file.label, compact ? 22 : 28)}
                </div>
                {index < 2 ? (
                  <div style={{marginTop: 4, fontSize: compact ? 13 : 14, lineHeight: 1.12, color: palette.mist, fontWeight: 730}}>
                    {index === 0 ? '入口承诺' : '核心实现'}
                  </div>
                ) : null}
              </div>
            </div>
          );
        })}
      </div>
      {particles.map((particle, index) => (
        <div
          key={`memory-particle-${index}`}
          style={{
            position: 'absolute',
            left: particle.x,
            top: particle.y,
            width: compact ? 9 : 12,
            height: compact ? 9 : 12,
            borderRadius: 999,
            background: index % 3 === 0 ? palette.cyan : index % 3 === 1 ? palette.green : palette.amber,
            boxShadow: `0 0 ${compact ? 18 : 26}px ${index % 3 === 0 ? palette.cyan : index % 3 === 1 ? palette.green : palette.amber}`,
            opacity: clamp(particle.opacity),
            transform: `scale(${particle.scale})`,
          }}
        />
      ))}
      {nodes.map(([label, detail, tone], index) => {
        if (index === 1) {
          return null;
        }
        const enter = spring({frame: localFrame - 10 - index * 12, fps, config: {damping: 22, stiffness: 116}});
        const hot = build * nodes.length >= index + 0.64;
        return (
          <div
            key={label}
            style={{
              position: 'absolute',
              left: positions[index][0],
              top: positions[index][1],
              width: compact ? 218 : 230,
              minHeight: compact ? 58 : 66,
              padding: compact ? '12px 0 12px 16px' : '13px 0 13px 18px',
              borderLeft: `5px solid ${tone}`,
              background: `linear-gradient(90deg, ${tone}${hot ? '2a' : '14'}, transparent 74%)`,
              color: palette.ivory,
              boxShadow: hot ? `0 20px 54px ${tone}18` : 'none',
              opacity: soft(enter, 0.66),
              transform: `translateY(${(1 - enter) * 18 + Math.sin(frame / 82 + index) * 3}px)`,
            }}
          >
            <div style={{fontSize: compact ? 13 : 14, fontWeight: 980, opacity: 0.72}}>workflow edge</div>
            <div style={{marginTop: 7, fontSize: compact ? 23 : 26, lineHeight: 0.98, fontWeight: 980}}>{label}</div>
          </div>
        );
      })}
      <div
        style={{
          position: 'absolute',
          left: compact ? 38 : 254,
          right: compact ? 38 : 64,
          bottom: compact ? 30 : 22,
          minHeight: compact ? 92 : 78,
          padding: compact ? '12px 0 12px 20px' : '10px 0 10px 24px',
          background: 'transparent',
          color: palette.ivory,
          borderLeft: `5px solid ${palette.green}`,
          borderTop: `1px solid ${palette.green}55`,
          filter: `drop-shadow(0 24px 44px ${palette.green}24)`,
          opacity: soft(recall, 0.62),
        }}
      >
          <div style={{fontSize: compact ? 13 : 14, fontWeight: 980}}>architecture judgment</div>
        <div style={{marginTop: 7, fontSize: compact ? 23 : 25, lineHeight: 1.06, fontWeight: 930, textShadow: '0 10px 32px rgba(0,0,0,0.46)'}}>
          {clean(model.arc.practical_fit || '高频、结构化、可验收的任务才适合写成循环。', compact ? 42 : 52)}
        </div>
      </div>
    </div>
  );
};

const MemoryCoreHeroObject: React.FC<{
  model: ShowcaseModel;
  scene: ShowcaseScene;
  frame: number;
  localFrame: number;
  fps: number;
  sceneFrames: number;
  compact?: boolean;
}> = ({model, scene, frame, localFrame, fps, sceneFrames, compact}) => {
  const draw = interpolate(localFrame, [18, sceneFrames * 0.74], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  const core = spring({frame: localFrame - 18, fps, config: {damping: 25, stiffness: 92}});
  const scan = interpolate((frame % 150) / 150, [0, 1], [-160, 620]);
  const actions = workflowActionsFor(model);
  const footerLabels = [
    coreLabelFor(model, 12),
    guardLabelFor(model, 12),
    metricLabelFor(model, 12),
  ];
  const labels = [
    [actions[0][0], actions[0][1], palette.cyan, compact ? [32, 64] : [68, 158]],
    [actions[1][0], actions[1][1], scene.tone, compact ? [286, 124] : [438, 74]],
    [actions[2][0], actions[2][1], palette.amber, compact ? [314, 438] : [620, 332]],
  ] as const;
  const width = compact ? 520 : 760;
  const height = compact ? 650 : 560;
  return (
    <div style={{position: 'relative', height: compact ? 710 : 560, minHeight: 0, perspective: 1400}}>
      <svg width="100%" height="100%" viewBox={`0 0 ${width} ${height}`} style={{position: 'absolute', inset: 0, overflow: 'visible'}}>
        <defs>
          <linearGradient id="memoryHeroTrace" x1="0" x2="1">
            <stop offset="0%" stopColor={palette.cyan} />
            <stop offset="46%" stopColor={scene.tone} />
            <stop offset="100%" stopColor={palette.amber} />
          </linearGradient>
          <radialGradient id="memoryHeroGlow" cx="50%" cy="46%" r="58%">
            <stop offset="0%" stopColor={scene.tone} stopOpacity="0.44" />
            <stop offset="54%" stopColor={palette.green} stopOpacity="0.15" />
            <stop offset="100%" stopColor="transparent" stopOpacity="0" />
          </radialGradient>
          <linearGradient id="memoryHeroSlab" x1="0" x2="1" y1="0" y2="1">
            <stop offset="0%" stopColor={palette.ivory} stopOpacity="0.96" />
            <stop offset="44%" stopColor={scene.tone} stopOpacity="0.96" />
            <stop offset="100%" stopColor={palette.green} stopOpacity="0.96" />
          </linearGradient>
          <linearGradient id="memoryHeroScan" x1="0" x2="1">
            <stop offset="0%" stopColor="transparent" />
            <stop offset="50%" stopColor={palette.ivory} stopOpacity="0.42" />
            <stop offset="100%" stopColor="transparent" />
          </linearGradient>
        </defs>
        <ellipse cx={compact ? 276 : 384} cy={compact ? 320 : 282} rx={compact ? 222 : 286} ry={compact ? 156 : 176} fill="url(#memoryHeroGlow)" opacity="0.88" />
        <path
          d={compact ? 'M68 130 C226 42 404 140 418 286 C438 444 254 526 92 448' : 'M92 242 C214 50 444 58 544 216 C640 370 490 488 222 418'}
          fill="none"
          stroke="rgba(255,250,240,0.12)"
          strokeWidth={compact ? 24 : 28}
          strokeLinecap="round"
        />
        <path
          d={compact ? 'M68 130 C226 42 404 140 418 286 C438 444 254 526 92 448' : 'M92 242 C214 50 444 58 544 216 C640 370 490 488 222 418'}
          fill="none"
          stroke="url(#memoryHeroTrace)"
          strokeWidth={compact ? 8 : 9}
          strokeLinecap="round"
          strokeDasharray="1180"
          strokeDashoffset={1180 * (1 - draw)}
        />
        {[0, 1, 2, 3].map((layer) => {
          const offset = compact ? layer * 22 : layer * 28;
          const depth = Math.sin(frame / (88 + layer * 11)) * (compact ? 4 : 7);
          const top = compact ? 214 + offset + depth : 162 + offset + depth;
          const left = compact ? 126 + layer * 11 : 214 + layer * 16;
          const right = compact ? 478 - layer * 8 : 682 - layer * 12;
          const bottom = top + (compact ? 82 : 108);
          return (
            <path
              key={`memory-hero-slab-${layer}`}
              d={`M${left} ${top + 42} L${right - 130} ${top} L${right} ${top + 52} L${left + 132} ${bottom} Z`}
              fill={layer === 0 ? 'url(#memoryHeroSlab)' : layer === 1 ? `${scene.tone}28` : `${palette.green}18`}
              stroke={layer === 0 ? `${palette.ivory}b8` : layer === 1 ? `${scene.tone}72` : `${palette.green}54`}
              strokeWidth={layer === 0 ? 3 : 2}
              opacity={soft(core, 0.36) - layer * 0.08}
              transform={`translate(0 ${(1 - core) * (28 - layer * 4)})`}
            />
          );
        })}
        <path
          d={compact ? `M${scan} 190 L${scan + 86} 224 L${scan - 44} 526 L${scan - 124} 496 Z` : `M${scan} 120 L${scan + 128} 168 L${scan - 54} 520 L${scan - 176} 474 Z`}
          fill="url(#memoryHeroScan)"
          opacity="0.48"
        />
        <text x={compact ? 268 : 372} y={compact ? 282 : 242} textAnchor="middle" fill={palette.dark} fontSize={compact ? 42 : 64} fontWeight="990" opacity={soft(core, 0.72)}>{coreLabelFor(model, compact ? 10 : 12)}</text>
        <text x={compact ? 272 : 380} y={compact ? 328 : 296} textAnchor="middle" fill="#31495d" fontSize={compact ? 16 : 22} fontWeight="930" opacity={soft(core, 0.7)}>调度 / 检查 / 重跑</text>
      </svg>
      {labels.map(([kind, label, tone, pos], index) => {
        const enter = spring({frame: localFrame - 10 - index * 16, fps, config: {damping: 20, stiffness: 118}});
        return (
          <div
            key={kind}
            style={{
              position: 'absolute',
              left: pos[0],
              top: pos[1],
              display: 'grid',
              gridTemplateColumns: '54px 1fr',
              gap: 13,
              alignItems: 'center',
              opacity: soft(enter, 0.7),
              filter: `drop-shadow(0 20px 36px ${tone}20)`,
              transform: `translateY(${(1 - enter) * 16 + Math.sin(frame / 76 + index) * 3}px)`,
            }}
          >
            <div style={{height: 2, background: tone, boxShadow: `0 0 24px ${tone}`}} />
            <div>
              <div style={{fontSize: compact ? 13 : 14, color: tone, fontWeight: 980}}>{kind}</div>
              <div style={{marginTop: 4, fontSize: compact ? 25 : 30, color: palette.ivory, fontWeight: 980}}>{label}</div>
            </div>
          </div>
        );
      })}
      <div
        style={{
          position: 'absolute',
          left: compact ? 46 : 94,
          right: compact ? 46 : 76,
          bottom: compact ? 42 : 28,
          borderTop: `1px solid ${scene.tone}62`,
          paddingTop: 16,
          display: 'flex',
          justifyContent: 'space-between',
          color: palette.mist,
          fontSize: compact ? 16 : 18,
          fontWeight: 850,
        }}
      >
        <span>{footerLabels[0]}</span>
        <span>{footerLabels[1]}</span>
        <span>{footerLabels[2]}</span>
      </div>
    </div>
  );
};

const RepoArchitectureStack: React.FC<{
  model: ShowcaseModel;
  scene: ShowcaseScene;
  frame: number;
  localFrame: number;
  fps: number;
  sceneFrames: number;
}> = ({model, scene, frame, localFrame, fps, sceneFrames}) => {
  const build = interpolate(localFrame, [16, sceneFrames * 0.78], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  const stackEntry = spring({frame: localFrame - 10, fps, config: {damping: 24, stiffness: 96}});
  const depthSweep = interpolate(localFrame, [24, 156], [-180, 160], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  const workflowLayers = workflowNodesFor(model, scene);
  const layers = [
    [workflowLabel(workflowLayers[0][0], 'TASK', 8), workflowLayers[0][1], palette.cyan, 58, 364],
    [coreLabelFor(model, 8), workflowLayers[1][1], scene.tone, 224, 188],
    [guardLabelFor(model, 8), workflowLayers[2][1], palette.green, 446, 356],
    [metricLabelFor(model, 8), workflowLayers[3][1], palette.amber, 606, 166],
  ] as const;
  return (
    <div
      style={{
        position: 'relative',
        height: 620,
        minHeight: 0,
        perspective: 1500,
        transform: `perspective(1500px) translate3d(${(1 - stackEntry) * -46 + Math.sin(frame / 118) * 18}px, ${Math.cos(frame / 132) * 10}px, ${Math.sin(frame / 146) * 90}px) rotateX(${9 - stackEntry * 4 + Math.sin(frame / 160) * 2.2}deg) rotateY(${-15 + stackEntry * 8 + Math.sin(frame / 120) * 4.2}deg) scale(${1.02 + Math.sin(frame / 170) * 0.018})`,
        transformStyle: 'preserve-3d',
      }}
    >
      {[0, 1, 2].map((plane) => {
        const tone = plane === 0 ? palette.cyan : plane === 1 ? scene.tone : palette.green;
        return (
          <div
            key={`arch-parallax-plane-${plane}`}
            style={{
              position: 'absolute',
              left: 86 + plane * 132 + Math.sin(frame / (96 + plane * 22)) * (6 + plane * 3),
              top: 126 + plane * 82 + Math.cos(frame / (110 + plane * 18)) * (5 + plane * 2),
              width: 360 + plane * 34,
              height: 118 + plane * 28,
              borderRadius: 28,
              border: `1px solid ${tone}32`,
              background: `linear-gradient(135deg, ${tone}12, rgba(255,250,240,0.025))`,
              boxShadow: `0 34px 90px ${tone}0f`,
              transform: `rotateX(62deg) rotateZ(${-17 + plane * 6}deg) translateZ(${-60 + plane * 38}px)`,
              opacity: 0.48 - plane * 0.08,
            }}
          />
        );
      })}
      <svg width="100%" height="100%" viewBox="0 0 820 620" style={{position: 'absolute', inset: 0, overflow: 'visible'}}>
        <defs>
          <linearGradient id="repoArchitectureBeam" x1="0" x2="1">
            <stop offset="0%" stopColor={palette.cyan} />
            <stop offset="36%" stopColor={scene.tone} />
            <stop offset="68%" stopColor={palette.green} />
            <stop offset="100%" stopColor={palette.amber} />
          </linearGradient>
          <radialGradient id="repoArchitectureCore" cx="50%" cy="48%" r="56%">
            <stop offset="0%" stopColor={scene.tone} stopOpacity="0.38" />
            <stop offset="100%" stopColor="transparent" stopOpacity="0" />
          </radialGradient>
        </defs>
        <ellipse cx="396" cy="292" rx="330" ry="214" fill="url(#repoArchitectureCore)" />
        <path d="M78 430 C184 318 264 332 354 258 C474 160 588 286 720 150" fill="none" stroke="rgba(255,250,240,0.085)" strokeWidth="28" strokeLinecap="round" />
        <path d="M78 430 C184 318 264 332 354 258 C474 160 588 286 720 150" fill="none" stroke="url(#repoArchitectureBeam)" strokeWidth="7" strokeLinecap="round" strokeDasharray="1160" strokeDashoffset={1160 * (1 - build)} />
        <path d={`M${326 + depthSweep} 88 L${442 + depthSweep} 118 L${288 + depthSweep} 540 L${168 + depthSweep} 506 Z`} fill={`${scene.tone}12`} stroke={`${scene.tone}3a`} strokeWidth="2" opacity="0.72" />
        {[0, 1, 2].map((index) => (
          <path
            key={`stack-floor-${index}`}
            d={`M${142 + index * 86} ${486 - index * 84} L${620 + index * 16} ${422 - index * 76} L${716 + index * 8} ${486 - index * 40} L${236 + index * 76} ${552 - index * 50} Z`}
            fill={`rgba(255,250,240,${0.04 + index * 0.018})`}
            stroke="rgba(255,250,240,0.16)"
            strokeWidth="2"
          />
        ))}
        {layers.map(([label, _detail, tone, left, top], index) => {
          const enter = spring({frame: localFrame - index * 11, fps, config: {damping: 21, stiffness: 112}});
          const hot = build * layers.length >= index + 0.55;
          const x = Number(left);
          const y = Number(top) + Math.sin(frame / 78 + index) * 5;
          const plate = index === 1 ? 'M0 56 L138 10 L228 54 L88 112 Z' : 'M0 48 L112 14 L178 50 L66 92 Z';
          const labelX = index === 1 ? 54 : 36;
          const labelY = index === 1 ? 61 : 53;
          return (
            <g key={`repo-arch-plate-${label}`} transform={`translate(${x} ${y})`} opacity={soft(enter, 0.7)}>
              <path
                d={plate}
                fill={hot ? tone : `${tone}2f`}
                stroke={tone}
                strokeWidth="2"
              />
              <path d={index === 1 ? 'M18 54 L138 18 L208 54' : 'M14 47 L112 19 L164 50'} fill="none" stroke="rgba(255,250,240,0.36)" strokeWidth="3" strokeLinecap="round" />
              <text x={labelX} y={labelY} fill={hot ? palette.dark : palette.ivory} fontSize={index === 1 ? 39 : 30} fontWeight="990">{label}</text>
            </g>
          );
        })}
      </svg>
    </div>
  );
};

const MemoryMechanismDiagram: React.FC<{
  model: ShowcaseModel;
  scene: ShowcaseScene;
  frame: number;
  localFrame: number;
  fps: number;
  sceneFrames: number;
  compact?: boolean;
}> = ({model, scene, frame, localFrame, fps, sceneFrames, compact}) => {
  const progress = interpolate(localFrame, [14, sceneFrames * 0.82], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  const coreLift = spring({frame: localFrame - 24, fps, config: {damping: 24, stiffness: 94}});
  const split = interpolate(localFrame, [20, 128], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  const workflowNodes = workflowNodesFor(model, scene);
  const actions = workflowActionsFor(model);
  const steps = [
    [actions[0][0], actions[0][1], model.arc.hook || workflowNodes[0][1], palette.cyan],
    [actions[1][0], actions[1][1], model.arc.mechanism || workflowNodes[1][1], scene.tone],
    [actions[2][0], actions[2][1], model.arc.failure_boundary || workflowNodes[2][1], palette.green],
    ['output', metricLabelFor(model, 10), model.arc.practical_fit || workflowNodes[3][1], palette.amber],
  ];
  const width = compact ? 520 : 850;
  const height = compact ? 690 : 610;
  return (
    <div style={{position: 'relative', height: compact ? 710 : 620, overflow: 'hidden'}}>
      <svg width="100%" height="100%" viewBox={`0 0 ${width} ${height}`} style={{position: 'absolute', inset: 0}}>
        <defs>
          <linearGradient id="memoryMechanismBeam" x1="0" x2="1">
            <stop offset="0%" stopColor={palette.cyan} />
            <stop offset="36%" stopColor={scene.tone} />
            <stop offset="68%" stopColor={palette.green} />
            <stop offset="100%" stopColor={palette.amber} />
          </linearGradient>
          <linearGradient id="memoryMechanismCore" x1="0" x2="1" y1="0" y2="1">
            <stop offset="0%" stopColor={palette.ivory} />
            <stop offset="48%" stopColor={scene.tone} />
            <stop offset="100%" stopColor={palette.green} />
          </linearGradient>
        </defs>
        <path d={compact ? 'M72 86 C330 84 340 256 142 298 C50 318 64 470 430 516' : 'M58 306 C202 92 346 92 430 272 C504 430 626 426 786 166'} fill="none" stroke="rgba(255,250,240,0.13)" strokeWidth={compact ? 24 : 30} strokeLinecap="round" />
        <path d={compact ? 'M72 86 C330 84 340 256 142 298 C50 318 64 470 430 516' : 'M58 306 C202 92 346 92 430 272 C504 430 626 426 786 166'} fill="none" stroke="url(#memoryMechanismBeam)" strokeWidth={compact ? 8 : 9} strokeLinecap="round" strokeDasharray="1180" strokeDashoffset={1180 * (1 - progress)} />
        {[0, 1, 2, 3].map((layer) => {
          const x = compact ? 160 + layer * 28 : 270 + layer * 44;
          const y = compact ? 256 + layer * 30 : 236 + layer * 34;
          const lift = (1 - split) * (layer % 2 === 0 ? 28 : -22) + Math.sin(frame / (80 + layer * 13)) * 4;
          return (
            <path
              key={`mechanism-slice-${layer}`}
              d={compact ? `M${x} ${y + lift} L${x + 190} ${y - 52 + lift} L${x + 260} ${y + lift} L${x + 72} ${y + 56 + lift} Z` : `M${x} ${y + lift} L${x + 232} ${y - 72 + lift} L${x + 324} ${y + lift} L${x + 92} ${y + 78 + lift} Z`}
              fill={layer === 0 ? 'url(#memoryMechanismCore)' : layer === 1 ? `${scene.tone}28` : layer === 2 ? `${palette.green}20` : `${palette.amber}16`}
              stroke={layer === 0 ? `${palette.ivory}cc` : `${tones[layer]}70`}
              strokeWidth={layer === 0 ? 3 : 2}
              opacity={soft(coreLift, 0.34) - layer * 0.07}
            />
          );
        })}
        <text x={compact ? 292 : 430} y={compact ? 296 : 284} textAnchor="middle" fill={palette.dark} fontSize={compact ? 28 : 39} fontWeight="990" opacity={soft(coreLift, 0.7)}>{coreLabelFor(model, compact ? 10 : 12)}</text>
        <text x={compact ? 292 : 430} y={compact ? 332 : 332} textAnchor="middle" fill="#40586b" fontSize={compact ? 18 : 25} fontWeight="920" opacity={soft(coreLift, 0.66)}>调度 / 检查 / 重跑</text>
      </svg>
      {steps.map(([phase, label, detail, tone], index) => {
        const enter = spring({frame: localFrame - 10 - index * 13, fps, config: {damping: 21, stiffness: 114}});
        const hot = progress * steps.length > index + 0.55;
        const pos = compact
          ? [
            [32, 44],
            [226, 164],
            [58, 318],
            [246, 500],
          ][index]
          : [
            [44, 256],
            [262, 88],
            [422, 302],
            [628, 148],
          ][index];
        return (
          <div
            key={phase}
            style={{
              position: 'absolute',
              left: pos[0],
              top: pos[1],
              width: compact ? 214 : index === 1 ? 282 : 250,
              minHeight: compact ? 86 : 96,
              padding: compact ? '12px 0 12px 18px' : '16px 0 16px 22px',
              borderLeft: `5px solid ${tone}`,
              background: 'transparent',
              color: palette.ivory,
              filter: hot ? `drop-shadow(0 22px 44px ${tone}28)` : 'none',
              opacity: soft(enter, 0.68),
              transform: `translateY(${(1 - enter) * 18 + Math.sin(frame / 78 + index) * 4}px) rotate(${index === 0 ? -2 : index === 3 ? 2 : 0}deg)`,
            }}
          >
            <div style={{fontSize: compact ? 13 : 14, fontWeight: 980, letterSpacing: 0, opacity: 0.84}}>{phase}</div>
            <div style={{marginTop: 10, fontSize: compact ? 24 : 31, lineHeight: 1.0, fontWeight: 980}}>{label}</div>
              <div style={{marginTop: 10, fontSize: compact ? 16 : 18, lineHeight: 1.17, fontWeight: 760, color: palette.mist}}>
              {clean(detail, compact ? 48 : 60)}
            </div>
          </div>
        );
      })}
      {Array.from({length: compact ? 7 : 10}).map((_, index) => {
        const t = (frame / 64 + index / 10) % 1;
        const left = compact ? 60 + Math.sin(t * 5.7) * 118 + t * 320 : 74 + t * 700;
        const top = compact ? 92 + t * 456 + Math.sin(t * 8.2) * 44 : 288 + Math.sin(t * Math.PI * 2.1) * 145 - t * 86;
        const tone = index % 2 === 0 ? palette.green : scene.tone;
        return (
          <div
            key={`mechanism-packet-${index}`}
            style={{
              position: 'absolute',
              left,
              top,
              width: compact ? 10 : 13,
              height: compact ? 10 : 13,
              borderRadius: 999,
              background: tone,
              opacity: 0.18 + 0.58 * Math.sin(t * Math.PI),
              boxShadow: `0 0 ${compact ? 20 : 30}px ${tone}`,
            }}
          />
        );
      })}
    </div>
  );
};

const WorkflowLinearFlow: React.FC<{
  model: ShowcaseModel;
  scene: ShowcaseScene;
  frame: number;
  localFrame: number;
  fps: number;
  sceneFrames: number;
  compact?: boolean;
}> = ({model, scene, frame, localFrame, fps, sceneFrames, compact}) => {
  const draw = interpolate(localFrame, [14, sceneFrames * 0.76], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  const scan = interpolate((frame % 132) / 132, [0, 1], [-120, 680]);
  const activeLine = Math.min(3, Math.floor(interpolate(localFrame, [32, 138], [0, 4], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'})));
  const steps = [
    {label: '静态 prompt', detail: '一次输入', tone: palette.cyan, x: 52, y: 88},
    {label: coreLabelFor(model, 12), detail: '调度 Claude', tone: scene.tone, x: 288, y: 190},
    {label: guardLabelFor(model, 12), detail: '检查结果', tone: palette.coral, x: 92, y: 330},
    {label: metricLabelFor(model, 12), detail: '重跑或合并', tone: palette.amber, x: 332, y: 458},
  ];
  const terminalLines = ['while task_open:', '  claude.run(task)', '  gate.check(result)', '  retry() or merge_pr()'];
  return (
    <div style={{position: 'relative', height: compact ? 690 : 620, minHeight: 0, overflow: 'visible'}}>
      <svg width="100%" height="100%" viewBox="0 0 640 660" style={{position: 'absolute', inset: 0, overflow: 'visible'}}>
        <defs>
          <linearGradient id="workflowLinearPath" x1="0" x2="1">
            <stop offset="0%" stopColor={palette.cyan} />
            <stop offset="42%" stopColor={scene.tone} />
            <stop offset="70%" stopColor={palette.coral} />
            <stop offset="100%" stopColor={palette.amber} />
          </linearGradient>
          <radialGradient id="workflowLinearGlow" cx="52%" cy="45%" r="64%">
            <stop offset="0%" stopColor={scene.tone} stopOpacity="0.34" />
            <stop offset="100%" stopColor="transparent" stopOpacity="0" />
          </radialGradient>
        </defs>
        <ellipse cx="330" cy="320" rx="280" ry="230" fill="url(#workflowLinearGlow)" />
        <path d="M116 154 C220 96 304 132 354 224 C404 316 212 286 176 396 C146 488 312 530 480 518" fill="none" stroke="rgba(255,250,240,0.13)" strokeWidth="26" strokeLinecap="round" />
        <path d="M116 154 C220 96 304 132 354 224 C404 316 212 286 176 396 C146 488 312 530 480 518" fill="none" stroke="url(#workflowLinearPath)" strokeWidth="8" strokeLinecap="round" strokeDasharray="1120" strokeDashoffset={1120 * (1 - draw)} />
        <path d={`M${scan} 54 L${scan + 100} 94 L${scan - 112} 620 L${scan - 218} 584 Z`} fill={`${scene.tone}17`} stroke={`${scene.tone}3d`} strokeWidth="2" opacity="0.58" />
      </svg>
      {steps.map((step, index) => {
        const enter = spring({frame: localFrame - index * 15, fps, config: {damping: 22, stiffness: 118}});
        const hot = draw * steps.length > index + 0.45;
        return (
          <div
            key={step.label}
            style={{
              position: 'absolute',
              left: step.x,
              top: step.y,
              width: index === 1 ? 232 : 206,
              minHeight: 104,
              padding: '16px 18px',
              borderRadius: 24,
              background: hot ? step.tone : 'rgba(8,17,29,0.72)',
              border: `1px solid ${step.tone}`,
              color: hot ? palette.dark : palette.ivory,
              boxShadow: `0 26px 70px rgba(0,0,0,0.28), 0 0 70px ${step.tone}24`,
              opacity: soft(enter, 0.72),
              transform: `translateY(${(1 - enter) * 18 + Math.sin(frame / 76 + index) * 4}px) scale(${hot ? 1.035 : 0.98})`,
            }}
          >
            <div style={{fontSize: 15, fontWeight: 980, opacity: 0.78}}>{index === 0 ? 'input' : index === 1 ? 'loop' : index === 2 ? 'gate' : 'output'}</div>
            <div style={{marginTop: 8, fontSize: 27, lineHeight: 1.0, fontWeight: 990, overflowWrap: 'anywhere'}}>{step.label}</div>
            <div style={{marginTop: 8, fontSize: 16, lineHeight: 1.12, fontWeight: 780, color: hot ? '#30485c' : palette.mist}}>{step.detail}</div>
          </div>
        );
      })}
      <div
        style={{
          position: 'absolute',
          left: compact ? 48 : 78,
          right: compact ? 44 : 78,
          bottom: compact ? 20 : 8,
          minHeight: 148,
          borderRadius: 22,
          background: 'rgba(5,11,19,0.78)',
          border: `1px solid ${scene.tone}76`,
          boxShadow: `0 30px 86px rgba(0,0,0,0.34), 0 0 72px ${scene.tone}18`,
          overflow: 'hidden',
        }}
      >
        <div style={{height: 36, display: 'flex', alignItems: 'center', gap: 8, padding: '0 16px', borderBottom: '1px solid rgba(255,250,240,0.12)'}}>
          {[palette.coral, palette.amber, palette.green].map((color) => <span key={color} style={{width: 9, height: 9, borderRadius: 99, background: color}} />)}
          <span style={{marginLeft: 8, color: palette.mist, fontSize: 15, fontWeight: 900, fontFamily: 'SFMono-Regular, Menlo, Consolas, monospace'}}>loop-controller.ts</span>
        </div>
        <div style={{padding: '14px 18px', fontFamily: 'SFMono-Regular, Menlo, Consolas, monospace'}}>
          {terminalLines.map((line, index) => {
            const visible = index <= activeLine;
            return (
              <div key={line} style={{height: 25, color: visible ? (index === activeLine ? palette.ivory : palette.mist) : 'transparent', fontSize: 18, fontWeight: index === activeLine ? 900 : 760}}>
                {visible ? line : '.'}
                {visible && index === activeLine ? <span style={{color: scene.tone}}>_</span> : null}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
};

const HeroScene: React.FC<{model: ShowcaseModel; scene: ShowcaseScene; frame: number; localFrame: number; fps: number; sceneFrames: number; width: number; height: number}> = ({
  model,
  scene,
  frame,
  localFrame,
  fps,
  sceneFrames,
  width,
  height,
}) => {
  const isHorizontal = width > height;
  const enter = spring({frame: localFrame, fps, config: {damping: 24, stiffness: 102}});
  const path = interpolate(localFrame, [18, sceneFrames * 0.72], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  const repoMode = isRepoTopic(model);
  const searchMode = isSearchTopic(model) && !repoMode;
  const stageY = Math.sin(frame / 88) * 6;
  const heroHook = clean(model.arc.hook || model.title, isHorizontal ? 62 : 42);
  const heroDetail = clean(model.arc.mechanism || model.arc.practical_fit || model.metric, isHorizontal ? 112 : 70);
  const heroTitleSize = isHorizontal ? horizontalHeadlineSize(heroHook, 68, 58, 50) : 35;
  const heroDetailSize = isHorizontal ? horizontalHeadlineSize(heroDetail, 27, 24, 22) : 19;
  if (repoMode && isHorizontal) {
    return (
      <div style={{position: 'absolute', inset: 0, padding: '118px 72px 82px'}}>
        <div
          style={{
            position: 'absolute',
            left: 84,
            top: 132,
            width: 760,
            opacity: soft(enter, 0.76),
            transform: `translate3d(${(1 - enter) * -38}px, ${Math.sin(frame / 118) * 5}px, 0)`,
          }}
        >
          <div style={{fontSize: 22, color: scene.tone, fontWeight: 950}}>{scene.title || '流程控制改变工作边界'}</div>
          <div style={{marginTop: 20, fontSize: 82, lineHeight: 0.92, color: palette.ivory, fontWeight: 990, overflowWrap: 'anywhere', textShadow: '0 18px 70px rgba(0,0,0,0.38)'}}>
            {clean(model.arc.hook || model.title, 74)}
          </div>
          <div style={{marginTop: 28, maxWidth: 720, fontSize: 29, lineHeight: 1.14, color: palette.mist, fontWeight: 720}}>
            {clean(model.arc.mechanism || model.arc.practical_fit || model.metric, 126)}
          </div>
          <div style={{marginTop: 36, width: 610, maxWidth: '100%', height: 3, background: `linear-gradient(90deg, ${scene.tone}, ${palette.green}, transparent)`}}>
            <div style={{height: 11, width: pct(path), marginTop: -4, background: `linear-gradient(90deg, ${scene.tone}, ${palette.ivory})`, boxShadow: `0 0 34px ${scene.tone}55`}} />
          </div>
        </div>
        <div
          style={{
            position: 'absolute',
            right: 40,
            top: 106,
            width: 920,
            height: 710,
            transform: `perspective(1500px) rotateY(${interpolate(localFrame, [0, 80], [-14, -4], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'})}deg) translateX(${Math.sin(frame / 128) * 18}px) scale(1.04)`,
            transformOrigin: 'center',
          }}
        >
          <MemoryCoreHeroObject model={model} scene={scene} frame={frame} localFrame={localFrame} fps={fps} sceneFrames={sceneFrames} />
        </div>
      </div>
    );
  }
  if (!isHorizontal && !searchMode) {
    const callouts = ['调度 Claude', '检查结果', '失败重跑'];
    return (
      <div style={{position: 'absolute', inset: 0, padding: '150px 58px 610px'}}>
        <div style={{position: 'relative', zIndex: 2}}>
          <div style={{fontSize: 18, color: scene.tone, fontWeight: 950}}>先看两个画面</div>
          <div style={{marginTop: 14, fontSize: 42, lineHeight: 1.02, color: palette.ivory, fontWeight: 990, textShadow: '0 16px 60px rgba(0,0,0,0.38)'}}>
            Prompt 变成循环控制
          </div>
          <div style={{marginTop: 18, display: 'flex', gap: 10, flexWrap: 'wrap'}}>
            {callouts.map((item, index) => {
              const enter = spring({frame: localFrame - index * 8, fps, config: {damping: 22, stiffness: 118}});
              return (
                <span
                  key={item}
                  style={{
                    display: 'inline-block',
                    padding: '8px 12px',
                    borderRadius: 999,
                    background: index === 1 ? scene.tone : 'rgba(255,250,240,0.10)',
                    color: index === 1 ? palette.dark : palette.ivory,
                    border: `1px solid ${index === 1 ? scene.tone : 'rgba(255,250,240,0.18)'}`,
                    fontSize: 18,
                    fontWeight: 900,
                    opacity: soft(enter, 0.68),
                    transform: `translateY(${(1 - enter) * 12}px)`,
                  }}
                >
                  {item}
                </span>
              );
            })}
          </div>
        </div>
        <div style={{marginTop: 36}}>
          <WorkflowLinearFlow model={model} scene={scene} frame={frame} localFrame={localFrame} fps={fps} sceneFrames={sceneFrames} compact />
        </div>
      </div>
    );
  }
  return (
    <div style={{position: 'absolute', inset: 0, padding: isHorizontal ? '142px 78px 92px' : '138px 58px 610px'}}>
      <div style={{height: '100%', display: 'grid', gridTemplateColumns: isHorizontal ? '0.82fr 1.18fr' : '1fr', gap: isHorizontal ? 58 : 38, alignItems: 'center'}}>
        <div style={{opacity: soft(enter, 0.78), transform: `translateX(${(1 - enter) * -28}px)`}}>
          <div style={{fontSize: isHorizontal ? 22 : 18, color: scene.tone, fontWeight: 950}}>先把问题钉住</div>
          <div style={{marginTop: isHorizontal ? 20 : 14, maxWidth: isHorizontal ? 690 : 'none', fontSize: heroTitleSize, lineHeight: isHorizontal ? 1.03 : 1.04, color: palette.ivory, fontWeight: 980, overflowWrap: 'anywhere'}}>
            {heroHook}
          </div>
          <div style={{marginTop: isHorizontal ? 24 : 16, maxWidth: isHorizontal ? 680 : 780, fontSize: heroDetailSize, lineHeight: 1.18, color: palette.mist, fontWeight: 690}}>
            {heroDetail}
          </div>
          <div style={{marginTop: isHorizontal ? 34 : 18, width: isHorizontal ? 620 : 420, maxWidth: '100%', height: 7, borderRadius: 99, background: 'rgba(255,250,240,0.13)', overflow: 'hidden'}}>
            <div style={{height: '100%', width: pct(path), background: `linear-gradient(90deg, ${scene.tone}, ${palette.green}, ${palette.amber})`}} />
          </div>
        </div>
        {!isHorizontal ? (
          !searchMode ? (
            <MemoryCoreHeroObject model={model} scene={scene} frame={frame} localFrame={localFrame} fps={fps} sceneFrames={sceneFrames} compact />
          ) : (
          <SearchPipelineDiagram model={model} scene={scene} frame={frame} localFrame={localFrame} fps={fps} compact />
          )
        ) : null}
        {isHorizontal ? (
          searchMode ? (
            <SearchPipelineDiagram model={model} scene={scene} frame={frame} localFrame={localFrame} fps={fps} />
          ) : repoMode ? (
            <MemoryCoreHeroObject model={model} scene={scene} frame={frame} localFrame={localFrame} fps={fps} sceneFrames={sceneFrames} />
          ) : (
          <div style={{position: 'relative', height: 540, perspective: 1400, transform: `translateY(${stageY}px)`}}>
            <svg width="100%" height="100%" viewBox="0 0 760 540" style={{position: 'absolute', inset: 0, overflow: 'visible'}}>
              <defs>
                <linearGradient id="heroPath" x1="0" x2="1">
                  <stop offset="0%" stopColor={scene.tone} />
                  <stop offset="55%" stopColor={palette.green} />
                  <stop offset="100%" stopColor={palette.amber} />
                </linearGradient>
              </defs>
              <path d="M82 280 C180 110 310 420 404 244 C500 80 594 168 684 88" fill="none" stroke="rgba(255,250,240,0.16)" strokeWidth="22" strokeLinecap="round" />
              <path d="M82 280 C180 110 310 420 404 244 C500 80 594 168 684 88" fill="none" stroke="url(#heroPath)" strokeWidth="7" strokeLinecap="round" strokeDasharray="980" strokeDashoffset={980 * (1 - path)} />
            </svg>
            {(searchMode ? ['问题', '证据', '答案'] : ['问题', '机制', '判断']).map((label, index) => {
              const positions = [
                [74, 236],
                [356, 196],
                [622, 46],
              ];
              const itemEnter = spring({frame: localFrame - 14 - index * 14, fps, config: {damping: 20, stiffness: 118}});
              const object = model.objects[index % model.objects.length];
              return (
                <div
                  key={label}
                  style={{
                    position: 'absolute',
                    left: positions[index][0],
                    top: positions[index][1],
                    width: index === 1 ? 246 : 214,
                    padding: '18px 20px',
                    borderRadius: 24,
                    background: index === 1 ? object.tone : 'rgba(255,250,240,0.10)',
                    border: `1px solid ${index === 1 ? object.tone : 'rgba(255,250,240,0.18)'}`,
                    color: index === 1 ? palette.dark : palette.ivory,
                    boxShadow: `0 30px 86px rgba(0,0,0,0.25), 0 0 64px ${object.tone}22`,
                    opacity: soft(itemEnter, 0.74),
                    transform: `rotateX(${index === 1 ? 3 : 8}deg) rotateY(${index === 0 ? -12 : index === 2 ? 9 : 0}deg) translateY(${(1 - itemEnter) * 20}px)`,
                  }}
                >
                  <div style={{fontSize: 13, fontWeight: 980}}>{label}</div>
                  <div style={{marginTop: 9, fontSize: 24, lineHeight: 1.04, fontWeight: 960, overflowWrap: 'anywhere'}}>{clean(object.label, 36)}</div>
                  <div style={{marginTop: 9, fontSize: 16, lineHeight: 1.18, fontWeight: 760, color: index === 1 ? '#32475a' : palette.mist}}>{clean(object.detail, 46)}</div>
                </div>
              );
            })}
          </div>
          )
        ) : null}
      </div>
    </div>
  );
};

const MechanismScene: React.FC<{model: ShowcaseModel; scene: ShowcaseScene; frame: number; localFrame: number; fps: number; sceneFrames: number; width: number; height: number}> = ({
  model,
  scene,
  frame,
  localFrame,
  fps,
  sceneFrames,
  width,
  height,
}) => {
  const isHorizontal = width > height;
  const repoMode = isRepoTopic(model);
  const searchMode = isSearchTopic(model) && !repoMode;
  const layers = [
    ['输入层', model.objects[0]?.label || '输入', palette.cyan],
    ['处理层', model.arc.mechanism || model.objects[1]?.detail || '机制', palette.amber],
    ['边界层', model.arc.failure_boundary || model.objects[2]?.detail || '失败边界', palette.coral],
    ['输出层', model.arc.judgment_framework || '判断框架', palette.green],
  ];
  const build = interpolate(localFrame, [20, sceneFrames * 0.75], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  if (repoMode && isHorizontal) {
    const reveal = spring({frame: localFrame - 6, fps, config: {damping: 26, stiffness: 92}});
    return (
      <div style={{position: 'absolute', inset: 0, padding: '122px 72px 88px'}}>
        <div
          style={{
            position: 'absolute',
            left: 74,
            top: 118,
            right: 72,
            height: 650,
            transform: `perspective(1500px) translate3d(${Math.sin(frame / 132) * -20}px, ${Math.cos(frame / 148) * 8}px, 0) rotateY(${interpolate(localFrame, [0, 94], [8, 1.5], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'})}deg)`,
            transformStyle: 'preserve-3d',
          }}
        >
          <MemoryMechanismDiagram model={model} scene={scene} frame={frame} localFrame={localFrame} fps={fps} sceneFrames={sceneFrames} />
        </div>
        <div
          style={{
            position: 'absolute',
            left: 96,
            bottom: 108,
            width: 760,
            opacity: soft(reveal, 0.72),
            transform: `translateY(${(1 - reveal) * 26}px)`,
          }}
        >
          <div style={{fontSize: 20, color: scene.tone, fontWeight: 950}}>机制不是结论，是因果链</div>
          <div style={{marginTop: 18, fontSize: 52, lineHeight: 1.0, color: palette.ivory, fontWeight: 980, textShadow: '0 14px 60px rgba(0,0,0,0.36)'}}>
            {clean(model.arc.mechanism || model.metric, 92)}
          </div>
          <div style={{marginTop: 20, fontSize: 25, lineHeight: 1.16, color: palette.mist, fontWeight: 720}}>
            {clean(model.arc.architecture_position || model.metric, 102)}
          </div>
        </div>
      </div>
    );
  }
  if (!isHorizontal && !searchMode) {
    return (
      <div style={{position: 'absolute', inset: 0, padding: '150px 58px 610px'}}>
        <div style={{position: 'relative', zIndex: 2}}>
          <div style={{fontSize: 18, color: scene.tone, fontWeight: 950}}>机制展开</div>
          <div style={{marginTop: 14, fontSize: 39, lineHeight: 1.04, color: palette.ivory, fontWeight: 980}}>
            {clean(model.arc.mechanism || '循环调度、检查、失败重跑', 54)}
          </div>
        </div>
        <div style={{marginTop: 28}}>
          <WorkflowLinearFlow model={model} scene={scene} frame={frame} localFrame={localFrame + 18} fps={fps} sceneFrames={sceneFrames} compact />
        </div>
      </div>
    );
  }
  return (
    <div style={{position: 'absolute', inset: 0, padding: isHorizontal ? '164px 72px 78px' : '138px 58px 610px'}}>
      <div style={{height: '100%', display: 'grid', gridTemplateColumns: isHorizontal ? '0.8fr 1.2fr' : '1fr', gap: 40, alignItems: 'center'}}>
        <div>
          <div style={{fontSize: 20, color: scene.tone, fontWeight: 950}}>机制不是结论，是因果链</div>
          <div style={{marginTop: 22, fontSize: isHorizontal ? 58 : 44, lineHeight: 1.0, color: palette.ivory, fontWeight: 970}}>
            {clean(model.arc.mechanism || model.metric, 90)}
          </div>
          <div style={{marginTop: 26, fontSize: isHorizontal ? 27 : 23, lineHeight: 1.22, color: palette.mist, fontWeight: 680}}>
            {clean(model.arc.architecture_position || model.metric, 96)}
          </div>
        </div>
        {!isHorizontal ? (
          !searchMode ? (
            <RepoSystemDiagram model={model} scene={scene} frame={frame} localFrame={localFrame} fps={fps} compact />
          ) : (
          <SearchPipelineDiagram model={model} scene={scene} frame={frame} localFrame={localFrame} fps={fps} compact />
          )
        ) : null}
        {isHorizontal ? (
          searchMode ? (
            <SearchPipelineDiagram model={model} scene={scene} frame={frame} localFrame={localFrame} fps={fps} />
          ) : repoMode ? (
            <MemoryMechanismDiagram model={model} scene={scene} frame={frame} localFrame={localFrame} fps={fps} sceneFrames={sceneFrames} />
          ) : (
          <div style={{position: 'relative', height: 570, perspective: 1500}}>
            <svg width="100%" height="100%" viewBox="0 0 860 570" style={{position: 'absolute', inset: 0}}>
              <defs>
                <linearGradient id="mechanismLine" x1="0" x2="1">
                  <stop offset="0%" stopColor={palette.cyan} />
                  <stop offset="50%" stopColor={scene.tone} />
                  <stop offset="100%" stopColor={palette.green} />
                </linearGradient>
              </defs>
              <path d="M140 292 C250 128 390 150 486 292 C570 416 660 420 748 250" fill="none" stroke="rgba(255,250,240,0.14)" strokeWidth="20" strokeLinecap="round" />
              <path d="M140 292 C250 128 390 150 486 292 C570 416 660 420 748 250" fill="none" stroke="url(#mechanismLine)" strokeWidth="6" strokeLinecap="round" strokeDasharray="1060" strokeDashoffset={1060 * (1 - build)} />
            </svg>
            {layers.map(([label, detail, tone], index) => {
              const enter = spring({frame: localFrame - 10 - index * 12, fps, config: {damping: 21, stiffness: 116}});
              const x = 88 + index * 168;
              const y = 96 + index * 72;
              return (
                <div
                  key={label}
                  style={{
                    position: 'absolute',
                    left: x,
                    top: y,
                    width: 270,
                    minHeight: 118,
                    borderRadius: 28,
                    padding: '22px 24px',
                    background: index === 1 ? tone : 'rgba(255,250,240,0.09)',
                    border: `1px solid ${tone}`,
                    color: index === 1 ? palette.dark : palette.ivory,
                    boxShadow: `0 ${28 + index * 5}px ${70 + index * 8}px rgba(0,0,0,0.24), 0 0 80px ${tone}1f`,
                    opacity: soft(enter, 0.74),
                    transform: `translate3d(${(1 - enter) * 16}px, ${Math.sin(frame / 80 + index) * 5}px, ${index * 22}px) rotateX(${8 - index * 2}deg) rotateY(${-10 + index * 5}deg)`,
                  }}
                >
                  <div style={{fontSize: 14, fontWeight: 980}}>{label}</div>
                  <div style={{marginTop: 12, fontSize: 23, lineHeight: 1.08, fontWeight: 900}}>{clean(detail, 56)}</div>
                </div>
              );
            })}
          </div>
          )
        ) : null}
      </div>
    </div>
  );
};

const ArchitectureScene: React.FC<{model: ShowcaseModel; scene: ShowcaseScene; frame: number; localFrame: number; fps: number; sceneFrames: number; width: number; height: number}> = ({
  model,
  scene,
  frame,
  localFrame,
  fps,
  sceneFrames,
  width,
  height,
}) => {
  const isHorizontal = width > height;
  const repoMode = isRepoTopic(model);
  const searchMode = isSearchTopic(model) && !isRepoTopic(model);
  const diagramEntry = spring({frame: localFrame - 8, fps, config: {damping: 24, stiffness: 94}});
  const diagramYaw = interpolate(localFrame, [0, 34, sceneFrames - 34, sceneFrames], [searchMode ? -8 : -10, -3, 2, 7], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const nodes = searchMode
    ? [
      ['意图', '用户问题被拆成任务', palette.cyan],
      ['检索', '多路查询拉证据', palette.amber],
      ['合成', 'RAG 压缩成答案', palette.green],
      ['边界', '来源弱时失败', palette.coral],
      ['判断', '给出可用框架', palette.plum],
    ]
    : model.objects.slice(0, 5).map((object, index) => [clean(object.label, 18), clean(object.detail, 30), object.tone]);
  const route = interpolate(localFrame, [16, sceneFrames * 0.82], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  return (
    <div style={{position: 'absolute', inset: 0, padding: isHorizontal ? '162px 72px 82px' : '138px 58px 610px'}}>
      <div style={{height: '100%', display: 'grid', gridTemplateColumns: isHorizontal ? (repoMode ? '1fr' : '1.1fr 0.9fr') : '1fr', gap: 40}}>
        <div
          style={{
            position: 'relative',
            minHeight: 0,
            transform: `perspective(1500px) rotateX(${5 - diagramEntry * 2}deg) rotateY(${diagramYaw}deg) translateX(${(1 - diagramEntry) * -22}px)`,
            transformStyle: 'preserve-3d',
          }}
        >
          {repoMode ? (
            <RepoArchitectureStack model={model} scene={scene} frame={frame} localFrame={localFrame} fps={fps} sceneFrames={sceneFrames} />
          ) : (
            <>
              <svg width="100%" height="100%" viewBox="0 0 980 610" style={{display: 'block'}}>
                <defs>
                  <linearGradient id="archRoute" x1="0" x2="1">
                    <stop offset="0%" stopColor={palette.cyan} />
                    <stop offset="36%" stopColor={palette.amber} />
                    <stop offset="70%" stopColor={palette.green} />
                    <stop offset="100%" stopColor={scene.tone} />
                  </linearGradient>
                </defs>
                <path d="M88 320 C230 118 360 486 494 284 C620 98 756 172 890 92" fill="none" stroke="rgba(255,250,240,0.12)" strokeWidth="28" strokeLinecap="round" />
                <path d="M88 320 C230 118 360 486 494 284 C620 98 756 172 890 92" fill="none" stroke="url(#archRoute)" strokeWidth="8" strokeLinecap="round" strokeDasharray="1220" strokeDashoffset={1220 * (1 - route)} />
              </svg>
              {nodes.map(([label, detail, tone], index) => {
                const positions = [
                  [44, 284],
                  [222, 142],
                  [416, 326],
                  [624, 164],
                  [784, 58],
                ];
                const enter = spring({frame: localFrame - index * 13, fps, config: {damping: 22, stiffness: 112}});
                const hot = route * nodes.length >= index + 0.7;
                return (
                  <div
                    key={`${label}-${index}`}
                    style={{
                      position: 'absolute',
                      left: positions[index][0],
                      top: positions[index][1],
                      width: 190,
                      padding: '17px 18px',
                      borderRadius: 22,
                      background: hot ? tone : 'rgba(255,250,240,0.08)',
                      border: `1px solid ${tone}`,
                      color: hot ? palette.dark : palette.ivory,
                      boxShadow: hot ? `0 26px 72px ${tone}29` : '0 16px 42px rgba(0,0,0,0.18)',
                      opacity: soft(enter, 0.72),
                      transform: `translate3d(0, ${Math.sin(frame / 78 + index) * 5}px, ${hot ? 34 + index * 8 : index * 6}px) rotateY(${-4 + index * 2}deg)`,
                    }}
                  >
                    <div style={{fontSize: 24, fontWeight: 970}}>{label}</div>
                    <div style={{marginTop: 8, fontSize: 17, lineHeight: 1.16, fontWeight: 750, color: hot ? '#334a5f' : palette.mist}}>{detail}</div>
                  </div>
                );
              })}
            </>
          )}
        </div>
        {isHorizontal && !repoMode ? (
          <div style={{display: 'grid', alignContent: 'center'}}>
            <div style={{fontSize: 18, color: scene.tone, fontWeight: 950}}>架构位置</div>
            <div style={{marginTop: 22, fontSize: 54, lineHeight: 1.02, color: palette.ivory, fontWeight: 970}}>
              {clean(model.arc.architecture_position || model.arc.mechanism || model.metric, 82)}
            </div>
            <div style={{marginTop: 28, fontSize: 25, lineHeight: 1.22, color: palette.mist, fontWeight: 680}}>
              {clean(model.arc.practical_fit || model.metric, 92)}
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
};

const RepoScene: React.FC<{model: ShowcaseModel; scene: ShowcaseScene; frame: number; localFrame: number; fps: number; sceneFrames: number; width: number; height: number}> = ({
  model,
  scene,
  frame,
  localFrame,
  fps,
  width,
  height,
}) => {
  const isHorizontal = width > height;
  if (isHorizontal) {
    return (
      <div style={{position: 'absolute', inset: 0, padding: '112px 72px 92px'}}>
        <div
          style={{
            position: 'absolute',
            left: 130,
            right: 90,
            top: 70,
            bottom: 70,
            transform: `perspective(1500px) rotateY(${interpolate(localFrame, [0, 96], [-6, 2], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'})}deg) translateX(${Math.sin(frame / 118) * 16}px) scale(1.02)`,
            transformStyle: 'preserve-3d',
          }}
        >
          <RepoSystemDiagram model={model} scene={scene} frame={frame} localFrame={localFrame} fps={fps} />
        </div>
      </div>
    );
  }
  return (
    <div style={{position: 'absolute', inset: 0, padding: isHorizontal ? '162px 72px 82px' : '138px 58px 610px'}}>
      <div style={{height: '100%', display: 'grid', gridTemplateColumns: isHorizontal ? '0.72fr 1.28fr' : '1fr', gap: 38, alignItems: 'center'}}>
        {isHorizontal ? (
          <div style={{display: 'grid', alignContent: 'center'}}>
            <div style={{fontSize: 18, color: scene.tone, fontWeight: 950}}>源码不是背景，是证据结构</div>
            <div style={{marginTop: 22, fontSize: 55, lineHeight: 1.02, color: palette.ivory, fontWeight: 970}}>
              {clean(model.arc.mechanism || model.arc.architecture_position || '把 repo 拆成入口、核心、运行和边界。', 88)}
            </div>
            <div style={{marginTop: 28, fontSize: 25, lineHeight: 1.22, color: palette.mist, fontWeight: 680}}>
              {clean(model.arc.practical_fit || model.metric, 94)}
            </div>
          </div>
        ) : null}
        <RepoSystemDiagram model={model} scene={scene} frame={frame} localFrame={localFrame} fps={fps} compact={!isHorizontal} />
      </div>
    </div>
  );
};

const CodeScene: React.FC<{model: ShowcaseModel; scene: ShowcaseScene; frame: number; localFrame: number; fps: number; sceneFrames: number; width: number; height: number}> = ({
  model,
  scene,
  localFrame,
  fps,
  width,
  height,
}) => {
  const isHorizontal = width > height;
  const key = topicText(model).toLowerCase();
  const repoMode = isRepoTopic(model);
  const repoFiles = repoFilesFor(model);
  const profile = /stagehand/.test(key)
    ? {
      file: 'browser-agent.ts',
      thesis: '把确定性浏览器控制接上 AI 的 act / extract 决策。',
      lines: ['const page = stagehand.context.pages()[0];', 'await page.goto(target);', 'await page.act("open the relevant path");', 'const result = await page.extract({ schema });', 'return decisionFrame(result);'],
    }
    : /\buv\b|astral-sh\/uv/.test(key)
      ? {
        file: 'uv workflow',
        thesis: '把依赖、环境和执行入口收进一条可复现命令链。',
        lines: ['$ uv init agent-lab', '$ uv add fastapi pytest', '$ uv run pytest', '$ uv sync --locked', '$ uv run python main.py'],
      }
      : /ai sdk|vercel/.test(key)
        ? {
          file: 'agent-route.ts',
          thesis: '把模型调用、工具和流式输出放进同一条类型安全链路。',
          lines: ['const result = streamText({', '  model, messages,', '  tools: { searchDocs },', '});', 'return result.toUIMessageStreamResponse();'],
        }
        : repoMode
          ? {
            file: clean(repoFiles[1]?.label || repoFiles[0]?.label || 'repo workflow', 34),
            thesis: clean(model.arc.practical_fit || '把仓库入口、核心模块、运行路径和失败样例连成一条可判断工作流。', 86),
            lines: [
              `$ inspect ${clean(repoFiles[0]?.label || 'README.md', 30)}`,
              `$ trace ${clean(repoFiles[1]?.label || 'core module', 30)}`,
              `$ run ${clean(repoFiles[2]?.label || 'API / CLI', 30)}`,
              `$ compare ${clean(repoFiles[3]?.label || 'tests / evals', 30)}`,
              '$ decide fit-cost-boundary',
            ],
          }
        : {
          file: 'workflow.sh',
          thesis: '把证据入口、架构边界和失败样例串成可检查工作流。',
          lines: ['$ load primary-source', '$ map architecture-boundary', '$ compare fit cost failure', '$ write judgment-framework'],
        };
  const active = Math.min(profile.lines.length - 1, Math.floor(interpolate(localFrame, [8, 96], [0, profile.lines.length], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'})));
  const terminalEntry = spring({frame: localFrame - 2, fps, config: {damping: 18, stiffness: 220}});
  return (
    <div style={{position: 'absolute', inset: 0, padding: isHorizontal ? '166px 72px 82px' : '138px 58px 610px'}}>
      <div style={{height: '100%', display: 'grid', gridTemplateColumns: '1fr', gap: 36, placeItems: 'center'}}>
        <div
          style={{
            width: isHorizontal ? '78%' : '100%',
            maxWidth: 1320,
            borderRadius: 26,
            overflow: 'hidden',
            background: 'rgba(8,17,29,0.86)',
            border: `1px solid ${scene.tone}82`,
            boxShadow: `0 42px 120px rgba(0,0,0,0.34), 0 0 88px ${scene.tone}18`,
            transform: `perspective(1400px) translate3d(${(1 - terminalEntry) * -92}px, ${(1 - terminalEntry) * 16}px, ${(1 - terminalEntry) * -260}px) rotateY(${(1 - terminalEntry) * -14}deg)`,
            transformStyle: 'preserve-3d',
          }}
        >
          <div style={{height: 58, display: 'flex', alignItems: 'center', gap: 10, padding: '0 24px', borderBottom: '1px solid rgba(255,250,240,0.12)'}}>
            {[palette.coral, palette.amber, palette.green].map((color) => <span key={color} style={{width: 12, height: 12, borderRadius: 99, background: color}} />)}
            <span style={{marginLeft: 14, color: palette.ivory, fontSize: 19, fontWeight: 900, fontFamily: 'SFMono-Regular, Menlo, Consolas, monospace'}}>{profile.file}</span>
          </div>
          <div style={{padding: '34px 36px', fontFamily: 'SFMono-Regular, Menlo, Consolas, monospace'}}>
            {profile.lines.map((line, index) => {
              const enter = spring({frame: localFrame - 8 - index * 6, fps, config: {damping: 22, stiffness: 116}});
              const hot = index === active;
              return (
                <div
                  key={`${index}-${line}`}
                  style={{
                    display: 'grid',
                    gridTemplateColumns: '46px 1fr',
                    gap: 18,
                    minHeight: 54,
                    alignItems: 'center',
                    color: hot ? palette.ivory : palette.mist,
                    background: hot ? `${scene.tone}1e` : 'transparent',
                    borderLeft: hot ? `5px solid ${scene.tone}` : '5px solid transparent',
                    borderRadius: 12,
                    padding: '3px 12px',
                    opacity: soft(enter, 0.56),
                  }}
                >
                  <span style={{fontSize: 16, color: 'rgba(255,250,240,0.78)', textAlign: 'right', fontWeight: 760}}>{index + 1}</span>
                  <span style={{fontSize: 25, lineHeight: 1.18, whiteSpace: 'pre', color: /act|extract|streamText|uv run/.test(line) ? palette.green : hot ? palette.ivory : palette.mist}}>{line}</span>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
};

const MetricScene: React.FC<{model: ShowcaseModel; scene: ShowcaseScene; frame: number; localFrame: number; fps: number; sceneFrames: number; width: number; height: number}> = ({
  model,
  scene,
  frame,
  localFrame,
  fps,
  width,
  height,
}) => {
  const isHorizontal = width > height;
  const route = interpolate(localFrame, [18, 152], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  const sweep = interpolate((localFrame % 140) / 140, [0, 1], [-120, 680]);
  const nodes = [
    {label: metricLabelFor(model, 14), role: '吞吐量信号', detail: clean(metricObjectFor(model)?.detail || model.metric, 42), tone: palette.green, x: 86, y: 118},
    {label: coreLabelFor(model, 14), role: '循环机制', detail: clean(model.arc.mechanism || '调度、检查、失败重跑', 42), tone: scene.tone, x: 284, y: 268},
    {label: guardLabelFor(model, 14), role: '审查债务', detail: clean(model.arc.failure_boundary || '验收条件缺失时放大错误', 42), tone: palette.coral, x: 492, y: 118},
  ];
  return (
    <div style={{position: 'absolute', inset: 0, padding: isHorizontal ? '166px 72px 82px' : '138px 58px 610px'}}>
      <div style={{height: '100%', display: 'grid', gridTemplateColumns: isHorizontal ? '0.92fr 1.08fr' : '1fr', gap: 42, alignItems: 'center'}}>
        <div>
          <div style={{fontSize: 18, color: scene.tone, fontWeight: 950}}>不是排名，是取舍坐标</div>
          <div style={{marginTop: 22, fontSize: isHorizontal ? 56 : 43, lineHeight: 1.02, color: palette.ivory, fontWeight: 970}}>
            {clean(model.arc.tradeoff || model.arc.practical_fit || model.metric, 88)}
          </div>
          <div style={{marginTop: 28, fontSize: isHorizontal ? 26 : 22, color: palette.mist, lineHeight: 1.22, fontWeight: 680}}>
            {model.metric}
          </div>
        </div>
        <div style={{position: 'relative', height: isHorizontal ? 560 : 620, minHeight: 0, overflow: 'visible'}}>
          <svg width="100%" height="100%" viewBox="0 0 720 620" style={{position: 'absolute', inset: 0, overflow: 'visible'}}>
            <defs>
              <linearGradient id="metricTradeoffPath" x1="0" x2="1">
                <stop offset="0%" stopColor={palette.green} />
                <stop offset="46%" stopColor={scene.tone} />
                <stop offset="100%" stopColor={palette.coral} />
              </linearGradient>
              <radialGradient id="metricTradeoffGlow" cx="50%" cy="45%" r="62%">
                <stop offset="0%" stopColor={scene.tone} stopOpacity="0.34" />
                <stop offset="100%" stopColor="transparent" stopOpacity="0" />
              </radialGradient>
            </defs>
            <ellipse cx="360" cy="286" rx="320" ry="210" fill="url(#metricTradeoffGlow)" />
            {[0, 1, 2].map((layer) => (
              <path
                key={`metric-depth-${layer}`}
                d={`M${94 + layer * 40} ${438 - layer * 68} C${226 + layer * 20} ${214 - layer * 34} ${472 - layer * 12} ${510 - layer * 48} ${626 - layer * 28} ${188 + layer * 30}`}
                fill="none"
                stroke={layer === 1 ? 'url(#metricTradeoffPath)' : 'rgba(255,250,240,0.16)'}
                strokeWidth={layer === 1 ? 8 : 2}
                strokeLinecap="round"
                strokeDasharray={layer === 1 ? 1160 : '16 18'}
                strokeDashoffset={layer === 1 ? 1160 * (1 - route) : 0}
                opacity={0.74 - layer * 0.12}
              />
            ))}
            <path d={`M${sweep} 74 L${sweep + 116} 112 L${sweep - 88} 584 L${sweep - 202} 548 Z`} fill={`${scene.tone}18`} stroke={`${scene.tone}40`} strokeWidth="2" opacity="0.6" />
          </svg>
          {nodes.map((node, index) => {
            const enter = spring({frame: localFrame - index * 14, fps, config: {damping: 22, stiffness: 112}});
            const hot = route * nodes.length > index + 0.45;
            return (
              <div
                key={node.role}
                style={{
                  position: 'absolute',
                  left: node.x,
                  top: node.y,
                  width: index === 1 ? 226 : 202,
                  minHeight: 126,
                  padding: '18px 20px',
                  borderRadius: 26,
                  background: hot ? node.tone : 'rgba(8,17,29,0.72)',
                  border: `1px solid ${node.tone}`,
                  color: hot ? palette.dark : palette.ivory,
                  boxShadow: `0 28px 78px rgba(0,0,0,0.28), 0 0 76px ${node.tone}24`,
                  opacity: soft(enter, 0.72),
                  transform: `translateY(${(1 - enter) * 18 + Math.sin(frame / 74 + index) * 5}px) scale(${hot ? 1.035 : 0.98})`,
                }}
              >
                <div style={{fontSize: 16, fontWeight: 980, opacity: 0.82}}>{node.role}</div>
                <div style={{marginTop: 10, fontSize: 30, lineHeight: 1.0, fontWeight: 990, overflowWrap: 'anywhere'}}>{node.label}</div>
                <div style={{marginTop: 10, fontSize: 17, lineHeight: 1.16, fontWeight: 760, color: hot ? '#31485a' : palette.mist}}>{node.detail}</div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
};

const SearchDecisionDiagram: React.FC<{model: ShowcaseModel; scene: ShowcaseScene; frame: number; localFrame: number; fps: number; width: number; height: number}> = ({
  model,
  scene,
  frame,
  localFrame,
  fps,
  width,
  height,
}) => {
  const isHorizontal = width > height;
  const draw = interpolate(localFrame, [18, 150], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  const points = [
    ['多步推理', 155, 168, palette.green, model.arc.practical_fit || '跨来源、多约束、需要综合判断'],
    ['事实查询', 250, 392, palette.amber, '明确事实优先传统搜索结果'],
    ['来源质量', 525, 210, palette.cyan, '索引质量决定 RAG 输出上限'],
    ['失败边界', 628, 426, palette.coral, model.arc.failure_boundary || '来源弱时回答会空洞'],
  ];
  return (
    <div style={{position: 'relative', height: isHorizontal ? 610 : '100%', minHeight: 0}}>
      <svg width="100%" height="100%" viewBox="0 0 760 780" style={{position: 'absolute', inset: 0}}>
        <defs>
          <linearGradient id="decisionCurve" x1="0" x2="1">
            <stop offset="0%" stopColor={palette.green} />
            <stop offset="52%" stopColor={scene.tone} />
            <stop offset="100%" stopColor={palette.coral} />
          </linearGradient>
        </defs>
        <path d="M88 622 L88 106 M88 622 L686 622" stroke="rgba(255,250,240,0.28)" strokeWidth="3" strokeLinecap="round" />
        <text x="100" y="126" fill={palette.mist} fontSize="22" fontWeight="850">问题复杂度</text>
        <text x="520" y="596" fill={palette.mist} fontSize="22" fontWeight="850">来源确定性</text>
        <path d="M116 534 C248 268 402 158 668 132" fill="none" stroke="url(#decisionCurve)" strokeWidth="9" strokeLinecap="round" strokeDasharray="840" strokeDashoffset={840 * (1 - draw)} />
        <path d="M116 534 C238 520 350 486 654 482" fill="none" stroke={palette.amber} strokeWidth="5" strokeLinecap="round" strokeDasharray="720" strokeDashoffset={720 * (1 - draw)} opacity="0.7" />
        <rect x="118" y="112" width="264" height="92" rx="24" fill={`${palette.green}22`} stroke={palette.green} />
        <text x="142" y="148" fill={palette.ivory} fontSize="26" fontWeight="950">AI Mode 更有价值</text>
        <text x="142" y="180" fill={palette.mist} fontSize="17" fontWeight="720">复杂任务、跨源综合、需要推理链</text>
        <rect x="404" y="500" width="262" height="88" rx="24" fill="rgba(255,250,240,0.08)" stroke={palette.amber} />
        <text x="428" y="536" fill={palette.ivory} fontSize="25" fontWeight="950">传统搜索更直接</text>
        <text x="428" y="568" fill={palette.mist} fontSize="17" fontWeight="720">明确事实、导航、单一来源</text>
      </svg>
      {points.map(([label, rawX, rawY, tone, detail], index) => {
        const x = Number(rawX);
        const y = Number(rawY);
        const enter = spring({frame: localFrame - index * 12, fps, config: {damping: 22, stiffness: 116}});
        return (
          <div
            key={label}
            style={{
              position: 'absolute',
              left: x - 84,
              top: y - 42,
              width: 180,
              minHeight: 84,
              borderRadius: 22,
              padding: '14px 16px',
              background: index === 0 ? tone : 'rgba(8,17,29,0.66)',
              border: `1px solid ${tone}`,
              color: index === 0 ? palette.dark : palette.ivory,
              boxShadow: `0 22px 64px ${tone}22`,
              opacity: soft(enter, 0.7),
              transform: `translateY(${Math.sin(frame / 70 + index) * 4}px)`,
            }}
          >
            <div style={{fontSize: 24, fontWeight: 960}}>{label}</div>
            <div style={{marginTop: 8, fontSize: 16, lineHeight: 1.14, fontWeight: 760, color: index === 0 ? '#32495c' : palette.mist}}>{clean(detail, 42)}</div>
          </div>
        );
      })}
    </div>
  );
};

const RepoBoundaryDiagram: React.FC<{model: ShowcaseModel; scene: ShowcaseScene; frame: number; localFrame: number; fps: number; width: number; height: number}> = ({
  model,
  scene,
  frame,
  localFrame,
  fps,
  width,
  height,
}) => {
  const isHorizontal = width > height;
  const reveal = interpolate(localFrame, [10, 146], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  const scan = interpolate(localFrame, [34, 172], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  const dialTilt = interpolate(localFrame, [0, 190], [-18, 18], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  const corePulse = interpolate(Math.sin(frame / 34), [-1, 1], [0.96, 1.07]);
  const orbitShift = interpolate(frame % 180, [0, 180], [0, 560]);
  const anchors = [
    {key: 'fit', label: '适合', detail: clean(model.arc.practical_fit || coreLabelFor(model, 8), 8), tone: palette.green, x: 72, y: 362, path: 'M386 286 C320 302 232 326 148 390'},
    {key: 'simple', label: '可测', detail: guardLabelFor(model, 8), tone: palette.amber, x: 300, y: 80, path: 'M390 260 C382 206 392 154 402 116'},
    {key: 'cut', label: '风险', detail: clean(model.arc.failure_boundary || guardLabelFor(model, 8), 8), tone: palette.coral, x: 562, y: 362, path: 'M404 288 C476 304 570 332 670 390'},
  ];
  return (
    <div style={{position: 'absolute', inset: 0, padding: isHorizontal ? '142px 72px 124px' : '138px 58px 610px'}}>
      <div style={{height: '100%', display: 'grid', gridTemplateColumns: '1fr', gap: 44, alignItems: 'center'}}>
        <div style={{position: 'relative', height: isHorizontal ? 618 : 520, minHeight: 0, perspective: 920}}>
          <svg width="100%" height="100%" viewBox="0 0 780 620" style={{position: 'absolute', inset: 0, overflow: 'visible'}}>
            <defs>
              <linearGradient id="repoBoundarySurface" x1="0" x2="1">
                <stop offset="0%" stopColor={palette.green} stopOpacity="0.72" />
                <stop offset="52%" stopColor={scene.tone} stopOpacity="0.86" />
                <stop offset="100%" stopColor={palette.coral} stopOpacity="0.78" />
              </linearGradient>
              <linearGradient id="repoBoundaryOrbit" x1="0" x2="1">
                <stop offset="0%" stopColor={palette.cyan} stopOpacity="0.1" />
                <stop offset="46%" stopColor={scene.tone} stopOpacity="0.92" />
                <stop offset="100%" stopColor={palette.amber} stopOpacity="0.12" />
              </linearGradient>
              <radialGradient id="repoBoundaryGlow" cx="50%" cy="52%" r="56%">
                <stop offset="0%" stopColor={scene.tone} stopOpacity="0.42" />
                <stop offset="100%" stopColor="transparent" stopOpacity="0" />
              </radialGradient>
            </defs>
            <ellipse cx="390" cy="310" rx={304 * corePulse} ry={222 * corePulse} fill="url(#repoBoundaryGlow)" />
            <g transform={`rotate(${dialTilt} 390 310)`}>
              <ellipse cx="390" cy="326" rx="286" ry="118" fill="rgba(255,250,240,0.052)" stroke="rgba(255,250,240,0.22)" strokeWidth="2" />
              <ellipse cx="390" cy="326" rx="244" ry="94" fill="none" stroke="url(#repoBoundaryOrbit)" strokeWidth="6" strokeLinecap="round" strokeDasharray="180 560" strokeDashoffset={-orbitShift} />
              <path d="M178 350 L390 184 L638 348 L388 484 Z" fill="rgba(255,250,240,0.075)" stroke="url(#repoBoundarySurface)" strokeWidth="2.5" />
              <path d="M390 184 L390 484" stroke="rgba(255,250,240,0.16)" strokeWidth="2" strokeDasharray="8 12" />
              <path d="M178 350 L638 348" stroke="rgba(255,250,240,0.16)" strokeWidth="2" strokeDasharray="8 12" />
            </g>
            {anchors.map((anchor, index) => (
              <g key={`beam-${anchor.key}`} opacity={0.5 + reveal * 0.45}>
                <path d={anchor.path} fill="none" stroke={anchor.tone} strokeWidth="3" strokeLinecap="round" strokeDasharray="560" strokeDashoffset={560 * (1 - reveal)} />
                <circle cx={anchor.key === 'simple' ? 402 : anchor.key === 'fit' ? 148 : 670} cy={anchor.key === 'simple' ? 116 : 390} r={9 + Math.sin(frame / 23 + index) * 2} fill={anchor.tone} />
              </g>
            ))}
            <g transform={`translate(390 300) scale(${corePulse})`}>
              <circle r="108" fill={palette.paper} opacity="0.95" />
              <circle r="82" fill="none" stroke={scene.tone} strokeWidth="4" opacity="0.78" />
              <circle r="48" fill={scene.tone} opacity="0.18" />
              <text x="0" y="14" textAnchor="middle" fill={palette.dark} fontSize="30" fontWeight="990">{guardLabelFor(model, 8)}</text>
            </g>
            <path d="M256 536 C320 492 504 492 578 536" fill="none" stroke="rgba(255,250,240,0.22)" strokeWidth="2" strokeDasharray="10 12" />
            <rect x="318" y="526" width={158 * scan} height="5" rx="3" fill={scene.tone} opacity="0.78" />
          </svg>
          {anchors.map((anchor, index) => {
            const enter = spring({frame: localFrame - index * 16, fps, config: {damping: 22, stiffness: 112}});
            const hot = reveal * anchors.length > index + 0.58;
            return (
              <div
                key={anchor.key}
                style={{
                  position: 'absolute',
                  left: anchor.x,
                  top: anchor.y,
                  width: index === 1 ? 150 : 168,
                  color: palette.ivory,
                  borderLeft: `4px solid ${anchor.tone}`,
                  paddingLeft: 16,
                  opacity: soft(enter, 0.68),
                  filter: `drop-shadow(0 18px 40px ${anchor.tone}28)`,
                  transform: `translateY(${(1 - enter) * 18 + Math.sin(frame / 76 + index) * 5}px) scale(${hot ? 1.035 : 0.96})`,
                }}
              >
                <div style={{fontSize: 38, lineHeight: 0.96, fontWeight: 990}}>{anchor.label}</div>
                <div style={{marginTop: 10, fontSize: 28, lineHeight: 1.0, fontWeight: 930, color: anchor.tone}}>{anchor.detail}</div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
};

const DecisionScene: React.FC<{model: ShowcaseModel; scene: ShowcaseScene; frame: number; localFrame: number; fps: number; sceneFrames: number; width: number; height: number}> = ({
  model,
  scene,
  frame,
  localFrame,
  fps,
  width,
  height,
}) => {
  const isHorizontal = width > height;
  const searchMode = isSearchTopic(model) && !isRepoTopic(model);
  return (
    <div style={{position: 'absolute', inset: 0, padding: isHorizontal ? '166px 72px 82px' : '138px 58px 610px'}}>
      {searchMode ? (
        <SearchDecisionDiagram model={model} scene={scene} frame={frame} localFrame={localFrame} fps={fps} width={width} height={height} />
      ) : (
        <RepoBoundaryDiagram model={model} scene={scene} frame={frame} localFrame={localFrame} fps={fps} width={width} height={height} />
      )}
    </div>
  );
};

const TakeawayScene: React.FC<{model: ShowcaseModel; scene: ShowcaseScene; frame: number; localFrame: number; fps: number; sceneFrames: number; width: number; height: number}> = ({
  model,
  scene,
  frame,
  localFrame,
  fps,
  width,
  height,
}) => {
  const isHorizontal = width > height;
  const repoMode = isRepoTopic(model);
  const scale = interpolate(Math.sin(frame / 54), [-1, 1], [0.982, 1.018]);
  const steps = [
    ['01', '机制是否成立', model.arc.mechanism || '先看系统怎么产生结果。'],
    ['02', '位置是否合适', model.arc.architecture_position || '再看它放在哪一层。'],
    ['03', '边界是否可承受', model.arc.failure_boundary || '最后看失败成本。'],
  ];
  if (repoMode) {
    const reveal = interpolate(localFrame, [16, 154], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
    const lenses = [
      ['机制', coreLabelFor(model, 10), palette.cyan],
      ['验收', guardLabelFor(model, 10), scene.tone],
      ['指标', metricLabelFor(model, 10), palette.coral],
    ];
    return (
      <div style={{position: 'absolute', inset: 0, padding: isHorizontal ? '142px 72px 118px' : '138px 58px 610px'}}>
        <div style={{height: '100%', display: 'grid', gridTemplateColumns: '1fr', gap: 44, alignItems: 'center'}}>
          <div style={{position: 'relative', height: isHorizontal ? 660 : 430, minHeight: 0}}>
            <svg width="100%" height="100%" viewBox="0 0 720 570" style={{position: 'absolute', inset: 0, overflow: 'visible'}}>
              <defs>
                <linearGradient id="repoTakeawayRing" x1="0" x2="1">
                  <stop offset="0%" stopColor={palette.cyan} />
                  <stop offset="48%" stopColor={scene.tone} />
                  <stop offset="100%" stopColor={palette.coral} />
                </linearGradient>
              </defs>
              {[0, 1, 2].map((ring) => (
                <ellipse
                  key={`ring-${ring}`}
                  cx="330"
                  cy="292"
                  rx={190 + ring * 52}
                  ry={118 + ring * 34}
                  fill="none"
                  stroke={ring === 1 ? 'url(#repoTakeawayRing)' : 'rgba(255,250,240,0.18)'}
                  strokeWidth={ring === 1 ? 4 : 2}
                  strokeDasharray={ring === 1 ? '18 16' : undefined}
                  opacity={0.82 - ring * 0.12}
                  transform={`rotate(${frame / (ring === 1 ? 4.8 : -6.4) + ring * 28} 330 292)`}
                />
              ))}
              <path d="M128 292 C218 154 436 154 550 292 C452 430 234 430 128 292Z" fill="rgba(255,250,240,0.055)" stroke="rgba(255,250,240,0.18)" strokeWidth="2" />
              <path d="M128 292 C218 154 436 154 550 292 C452 430 234 430 128 292Z" fill="none" stroke="url(#repoTakeawayRing)" strokeWidth="7" strokeLinecap="round" strokeDasharray="1160" strokeDashoffset={1160 * (1 - reveal)} />
            </svg>
            <div
              style={{
                position: 'absolute',
                left: '50%',
                top: '50%',
                width: isHorizontal ? 252 : 224,
                height: isHorizontal ? 252 : 224,
                marginLeft: isHorizontal ? -126 : -112,
                marginTop: isHorizontal ? -126 : -112,
                borderRadius: 999,
                padding: isHorizontal ? 34 : 28,
                display: 'grid',
                alignContent: 'center',
                textAlign: 'center',
                background: palette.paper,
                color: palette.dark,
                boxShadow: '0 48px 130px rgba(0,0,0,0.34)',
                transform: `scale(${scale}) rotate(${Math.sin(frame / 92) * 1.4}deg)`,
              }}
            >
              <div style={{fontSize: 16, color: '#50677d', fontWeight: 950}}>最终判断</div>
              <div style={{marginTop: 14, fontSize: isHorizontal ? 42 : 30, lineHeight: 0.98, fontWeight: 980}}>{coreLabelFor(model, 8)}</div>
              <div style={{marginTop: 6, fontSize: isHorizontal ? 31 : 23, lineHeight: 1.02, fontWeight: 940, color: '#526779'}}>先过验收</div>
            </div>
            {lenses.map(([label, detail, tone], index) => {
              const enter = spring({frame: localFrame - index * 12, fps, config: {damping: 21, stiffness: 112}});
              const pos = [
                ['16%', '22%'],
                ['66%', '22%'],
                ['20%', '70%'],
              ][index];
              return (
                <div
                  key={label}
                  style={{
                    position: 'absolute',
                    left: pos[0],
                    top: pos[1],
                    width: index === 1 ? 238 : 220,
                    borderLeft: `4px solid ${tone}`,
                    paddingLeft: 17,
                    color: palette.ivory,
                    opacity: soft(enter, 0.72),
                    transform: `translateY(${(1 - enter) * 18 + Math.sin(frame / 80 + index) * 4}px)`,
                  }}
                >
                  <div style={{fontSize: 46, lineHeight: 0.95, fontWeight: 990, textShadow: '0 6px 22px rgba(0,0,0,0.42)'}}>{label}</div>
                  <div style={{marginTop: 14, fontSize: 28, lineHeight: 1.02, fontWeight: 940, color: palette.ivory, textShadow: '0 5px 18px rgba(0,0,0,0.4)'}}>{detail}</div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    );
  }
  return (
    <div style={{position: 'absolute', inset: 0, padding: isHorizontal ? '166px 72px 82px' : '138px 58px 610px'}}>
      <div style={{height: '100%', display: 'grid', gridTemplateColumns: isHorizontal ? '0.9fr 1.1fr' : '1fr', gap: 42, alignItems: 'center'}}>
        <div style={{position: 'relative', height: isHorizontal ? 500 : 380, display: 'grid', placeItems: 'center'}}>
          <div style={{position: 'absolute', width: isHorizontal ? 410 : 300, height: isHorizontal ? 410 : 300, borderRadius: 999, border: `2px solid ${scene.tone}`, transform: `scale(${scale})`, boxShadow: `0 0 90px ${scene.tone}22`}} />
          <div style={{position: 'relative', width: isHorizontal ? 300 : 240, height: isHorizontal ? 300 : 240, borderRadius: 999, display: 'grid', placeItems: 'center', textAlign: 'center', background: palette.paper, color: palette.dark, padding: 38, boxShadow: '0 44px 120px rgba(0,0,0,0.34)'}}>
            <div>
              <div style={{fontSize: 15, color: '#50677d', fontWeight: 950}}>带走一个判断顺序</div>
              <div style={{marginTop: 18, fontSize: isHorizontal ? 46 : 34, lineHeight: 0.96, fontWeight: 980}}>机制</div>
              <div style={{fontSize: isHorizontal ? 29 : 22, fontWeight: 900, color: '#5c6d7d'}}>再到</div>
              <div style={{fontSize: isHorizontal ? 46 : 34, lineHeight: 0.96, fontWeight: 980}}>边界</div>
            </div>
          </div>
        </div>
        <div style={{display: 'grid', gap: isHorizontal ? 17 : 13}}>
            <div style={{fontSize: isHorizontal ? 44 : 30, color: palette.ivory, lineHeight: 1.04, fontWeight: 970}}>{clean(model.arc.takeaway || model.arc.judgment_framework || '把它当作一个可评估的系统位置，而不是一个口号。', isHorizontal ? 90 : 62)}</div>
            {steps.map(([num, label, detail], index) => {
              const enter = spring({frame: localFrame - 8 - index * 12, fps, config: {damping: 22, stiffness: 112}});
              return (
                <div key={num} style={{display: 'grid', gridTemplateColumns: isHorizontal ? '78px 1fr' : '62px 1fr', gap: isHorizontal ? 18 : 14, alignItems: 'center', padding: isHorizontal ? '18px 0' : '12px 0', borderBottom: '1px solid rgba(255,250,240,0.18)', opacity: soft(enter, 0.72)}}>
                  <div style={{width: isHorizontal ? 58 : 48, height: isHorizontal ? 58 : 48, borderRadius: 16, display: 'grid', placeItems: 'center', background: index === 1 ? scene.tone : 'rgba(255,250,240,0.12)', color: index === 1 ? palette.dark : palette.ivory, fontSize: isHorizontal ? 22 : 18, fontWeight: 960}}>{num}</div>
                  <div>
                    <div style={{fontSize: isHorizontal ? 27 : 21, color: palette.ivory, fontWeight: 940}}>{label}</div>
                    <div style={{marginTop: 7, fontSize: isHorizontal ? 22 : 18, color: palette.mist, lineHeight: 1.18, fontWeight: 740}}>{clean(detail, isHorizontal ? 76 : 54)}</div>
                  </div>
                </div>
              );
            })}
        </div>
      </div>
    </div>
  );
};

const renderScene = (
  model: ShowcaseModel,
  scene: ShowcaseScene,
  frame: number,
  localFrame: number,
  fps: number,
  sceneFrames: number,
  width: number,
  height: number,
) => {
  const props = {model, scene, frame, localFrame, fps, sceneFrames, width, height};
  if (/repo|file/i.test(scene.scene_type)) {
    return <RepoScene {...props} />;
  }
  if (/code|terminal/i.test(scene.scene_type)) {
    return <CodeScene {...props} />;
  }
  if (/architecture/i.test(scene.scene_type)) {
    return <ArchitectureScene {...props} />;
  }
  if (/metric|timeline/i.test(scene.scene_type)) {
    return <MetricScene {...props} />;
  }
  if (/decision/i.test(scene.scene_type)) {
    return <DecisionScene {...props} />;
  }
  if (/takeaway/i.test(scene.scene_type)) {
    return <TakeawayScene {...props} />;
  }
  if (/mechanism|repo/i.test(scene.scene_type)) {
    return <MechanismScene {...props} />;
  }
  return <HeroScene {...props} />;
};

export const ShowcaseDirectorVisual: React.FC<AgentVisualProps & {spec?: PremiumSpec; visualScenes?: PremiumScene[]}> = (props) => {
  const {frame, fps, durationInFrames, width, height, progress, spec, visualScenes} = props;
  const model = useShowcaseModel(props, spec, visualScenes);
  const isVertical = width <= height;
  const sceneCount = Math.max(1, model.scenes.length);
  const sceneFrames = durationInFrames / sceneCount;
  const activeIndex = Math.min(sceneCount - 1, Math.floor(clamp(progress, 0, 0.999) * sceneCount));
  const activeScene = model.scenes[activeIndex] ?? model.scenes[0];
  const cameraPan = interpolate(progress, [0, 1], [0, width > height ? -42 : -18], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  const cameraZoom = interpolate(Math.sin(frame / 180), [-1, 1], [1.0, width <= height ? 1.026 : 1.018]);
  return (
    <AbsoluteFill style={{overflow: 'hidden', color: palette.ivory, background: palette.ink}}>
      <CinematicBackdrop frame={frame} width={width} height={height} activeScene={activeScene} progress={progress} />
      {width > height ? <StageTitle model={model} activeScene={activeScene} frame={frame} width={width} height={height} /> : null}
      <div
        style={{
          position: 'absolute',
          inset: 0,
          transform: `translateX(${cameraPan}px) scale(${cameraZoom})`,
          transformOrigin: 'center center',
        }}
      >
        {model.scenes.map((scene, index) => {
          const previousSceneType = model.scenes[activeIndex - 1]?.scene_type || '';
          const activeIsTerminal = /code|terminal/i.test(activeScene.scene_type);
          const activeIsDecision = /decision/i.test(activeScene.scene_type);
          const enteringDecisionFromTerminal = activeIsDecision && /code|terminal/i.test(previousSceneType);
          const enteringTerminalFromArchitecture = activeIsTerminal && /architecture/i.test(previousSceneType);
          const previousIsArchitecture = index === activeIndex - 1 && /architecture/i.test(scene.scene_type);
          const previousIsTerminal = index === activeIndex - 1 && /code|terminal/i.test(scene.scene_type);
          const terminalDecisionHandoff = enteringDecisionFromTerminal && (index === activeIndex || previousIsTerminal);
          const architectureTerminalHandoff = enteringTerminalFromArchitecture && (index === activeIndex || previousIsArchitecture);
          const transitionFrames = width > height ? (terminalDecisionHandoff ? 42 : architectureTerminalHandoff ? 34 : 0) : 14;
          const activeStart = activeIndex * sceneFrames;
          const activeLocal = Math.max(0, frame - activeStart);
          const isPreviousOverlay = transitionFrames > 0 && index === activeIndex - 1 && activeLocal < transitionFrames;
          if (index !== activeIndex && !isPreviousOverlay) {
            return null;
          }
          const start = index * sceneFrames;
          const end = start + sceneFrames;
          const isTerminalScene = /code|terminal/i.test(scene.scene_type);
          const isDepthScene = /decision/i.test(scene.scene_type);
          const fadeInFrames = width > height
            ? isDepthScene
              ? (enteringDecisionFromTerminal ? 22 : 14)
              : isTerminalScene
                ? (enteringTerminalFromArchitecture ? 18 : 10)
                : 8
            : isDepthScene
              ? (enteringDecisionFromTerminal ? 38 : 24)
              : isTerminalScene
                ? (enteringTerminalFromArchitecture ? 28 : 14)
                : 18;
          const fadeOutFrames = /architecture/i.test(scene.scene_type) ? 12 : 24;
          const overlayProgress = isPreviousOverlay ? clamp(activeLocal / transitionFrames) : 0;
          const fadeFloor = width > height ? 0.52 : 0;
          const fade = isPreviousOverlay ? (1 - overlayProgress) * 0.06 : interpolate(frame, [start, start + fadeInFrames, end - fadeOutFrames, end], [fadeFloor, 1, 1, 0], {
            extrapolateLeft: 'clamp',
            extrapolateRight: 'clamp',
          });
          if (fade <= 0.001) {
            return null;
          }
          const localFrame = Math.min(sceneFrames - 1, Math.max(0, frame - start));
          const entry = spring({
            frame: localFrame,
            fps,
            config: isDepthScene ? (enteringDecisionFromTerminal ? {damping: 31, stiffness: 88} : {damping: 22, stiffness: 190}) : isTerminalScene ? (enteringTerminalFromArchitecture ? {damping: 27, stiffness: 112} : {damping: 16, stiffness: 280}) : {damping: 20, stiffness: 156},
          });
          const entryRailBase = isVertical ? 28 : isDepthScene ? (enteringDecisionFromTerminal ? 156 : 276) : isTerminalScene ? (enteringTerminalFromArchitecture ? 124 : 210) : 112;
          const entryYawBase = isVertical ? 0 : isDepthScene ? (enteringDecisionFromTerminal ? 10 : 22) : isTerminalScene ? (enteringTerminalFromArchitecture ? 6.5 : 13) : 7.5;
          const entryRail = (1 - entry) * (index % 2 === 0 ? entryRailBase : -entryRailBase);
          const entryYaw = (1 - entry) * (index % 2 === 0 ? -entryYawBase : entryYawBase);
          const entryPitch = isVertical ? 0 : (1 - entry) * (isDepthScene ? (enteringDecisionFromTerminal ? 4 : 8) : 0);
          const entryDepth = isVertical ? 0 : (1 - entry) * (isDepthScene ? (enteringDecisionFromTerminal ? -420 : -720) : isTerminalScene ? (enteringTerminalFromArchitecture ? -240 : -460) : -220);
          const sceneDrift = interpolate(frame, [start, end], [index % 2 === 0 ? (isVertical ? 6 : 18) : (isVertical ? -6 : -18), index % 2 === 0 ? (isVertical ? -4 : -12) : (isVertical ? 4 : 12)], {
            extrapolateLeft: 'clamp',
            extrapolateRight: 'clamp',
          });
          const exitDirection = index % 2 === 0 ? -1 : 1;
          const overlayX = terminalDecisionHandoff ? 82 : architectureTerminalHandoff ? 96 : 170;
          const overlayY = terminalDecisionHandoff ? -10 : architectureTerminalHandoff ? -8 : -24;
          const overlayZ = isVertical ? 0 : terminalDecisionHandoff ? -230 : architectureTerminalHandoff ? -180 : -360;
          const overlayYaw = isVertical ? 0 : terminalDecisionHandoff ? 3.5 : architectureTerminalHandoff ? 3 : 8;
          const organicX = sceneDrift + entryRail + overlayProgress * exitDirection * (isVertical ? 24 : overlayX) + Math.sin(localFrame / 92 + index * 0.9) * (isVertical ? 4 : isDepthScene ? 18 : 9);
          const organicY = Math.cos(localFrame / 116 + index) * (isVertical ? 3 : isDepthScene ? 10 : 5) + overlayProgress * (isVertical ? -4 : overlayY);
          const organicZ = isVertical ? 0 : entryDepth + overlayProgress * overlayZ + Math.sin(localFrame / 128 + index * 0.7) * (isDepthScene ? 72 : 18);
          const organicYaw = isVertical ? 0 : entryYaw + overlayProgress * exitDirection * overlayYaw + Math.sin(localFrame / 150 + index) * (isDepthScene ? 4.2 : 1.2);
          const transitionPlaneOpacity = !isVertical && isDepthScene ? interpolate(localFrame, enteringDecisionFromTerminal ? [0, 16, 64, 82] : [0, 10, 42, 58], enteringDecisionFromTerminal ? [0, 0.26, 0.18, 0] : [0, 0.34, 0.22, 0], {
            extrapolateLeft: 'clamp',
            extrapolateRight: 'clamp',
          }) : 0;
          return (
            <div
              key={scene.id}
              style={{
                position: 'absolute',
                inset: 0,
                opacity: fade,
                transform: isVertical
                  ? `translate3d(${organicX}px, ${organicY}px, 0) scale(${0.985 + entry * 0.015})`
                  : `perspective(1600px) translate3d(${organicX}px, ${organicY}px, ${organicZ}px) rotateX(${entryPitch}deg) rotateY(${organicYaw}deg) scale(${0.94 + fade * 0.014 + entry * 0.046})`,
                transformStyle: isVertical ? 'flat' : 'preserve-3d',
              }}
            >
              {isDepthScene ? (
                <div style={{position: 'absolute', inset: 0, pointerEvents: 'none', opacity: transitionPlaneOpacity, transformStyle: 'preserve-3d'}}>
                  {[0, 1, 2, 3].map((plane) => (
                    <div
                      key={`decision-depth-plane-${plane}`}
                      style={{
                        position: 'absolute',
                        left: `${-10 + plane * 16}%`,
                        top: `${16 + plane * 10}%`,
                        width: `${66 + plane * 8}%`,
                        height: `${22 + plane * 3}%`,
                        borderTop: `2px solid ${scene.tone}`,
                        background: `linear-gradient(90deg, transparent, ${scene.tone}26, transparent)`,
                        transform: `perspective(1400px) rotateX(${64 - plane * 4}deg) rotateZ(${-18 + plane * 9}deg) translate3d(${(1 - entry) * (260 - plane * 70)}px, ${(1 - entry) * (-80 + plane * 28)}px, ${(1 - entry) * (360 - plane * 96)}px)`,
                      }}
                    />
                  ))}
                </div>
              ) : null}
              {renderScene(model, scene, frame, localFrame, fps, sceneFrames, width, height)}
            </div>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};
