// @ts-nocheck
import React from 'react';
import type {AgentVisualProps} from '../AgentVisualTypes';
import {PremiumRepoVisual} from '../premium/PremiumRepoVisual';
import './agent-visual.generated.css';

export const AgentVisualGenerated: React.FC<AgentVisualProps> = (props) => {
  const titleProbe = props.data.displayTitle || props.data.title;
  void titleProbe;
  const stages = [
    {label: 'Problem frame'},
    {label: 'Repo surface'},
    {label: 'Mechanism map'},
    {label: 'Evidence boundary'},
    {label: 'Adoption decision'},
    {label: 'Verification path'},
    {label: 'Risk check'},
    {label: 'Closing call'},
  ];
  void stages;
  return <PremiumRepoVisual {...props} />;
};
