import React from 'react';
import 'katex/dist/katex.min.css';
import { InlineMath, BlockMath } from 'react-katex';

const LatexRenderer = ({ children, block = false }) => {
  const Component = block ? BlockMath : InlineMath;
  return <Component math={children} />;
};

export default LatexRenderer;