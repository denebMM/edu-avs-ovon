// Layout.js

import React from 'react';

const Layout = ({ children }) => {
  return (
    <div
      className="min-h-screen py-2 flex flex-col justify-center sm:py-4"
      style={{
        backgroundImage: `url('/image.webp')`,  // Image from the public folder
        backgroundSize: 'cover',
        backgroundPosition: 'center',
        backgroundRepeat: 'no-repeat',
        height: '100vh',  // Ensure full height is used
      }}
    >
      <div className="relative py-1 sm:max-w-7xl sm:mx-auto w-full px-2">
        <div className="relative px-3 py-3 bg-white dark:bg-gray-900 shadow-lg sm:rounded-3xl sm:p-6">
          <div className="max-w-full mx-auto text-black dark:text-white">
            {children}
          </div>
        </div>
      </div>
    </div>
  );
};

export default Layout;