import React from 'react';
import LatexRenderer from './LatexRenderer';

const SuggestedQuestions = ({ onQuestionClick }) => {
  const questions = [
    { text: "Can you explain the concept of derivatives?", latex: null },
    { text: "How do I approach solving linear equations?", latex: null },
    { text: "What's the intuition behind integration?", latex: null },
    { 
      text: "Could you break down the quadratic formula?", 
      latex: "ax^2 + bx + c = 0" 
    }
  ];

  return (
    <div className="grid grid-cols-2 gap-3 mb-4" aria-label="Suggested questions">
      {questions.map((question, index) => (
        <button
          key={index}
          onClick={() => onQuestionClick(question.text + (question.latex ? ` $$${question.latex}$$` : ''))}
          className="bg-white dark:bg-gray-700 py-2 px-3 rounded-lg shadow-sm text-left hover:bg-gray-50 dark:hover:bg-gray-600 transition-colors text-sm border border-gray-200 dark:border-gray-600 text-black dark:text-white"
          aria-label={`Ask question: ${question.text}`}
        >
          <div>{question.text}</div>
          {question.latex && (
            <div className="mt-1 text-center">
              <LatexRenderer>{question.latex}</LatexRenderer>
            </div>
          )}
        </button>
      ))}
    </div>
  );
};

export default SuggestedQuestions;