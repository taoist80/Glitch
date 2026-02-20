#!/usr/bin/env node

/**
 * Glitch UI Connection Helper
 * 
 * Creates a local proxy server that forwards requests to the deployed AgentCore runtime.
 * 
 * Usage:
 *   pnpm check     - Check connection status
 *   pnpm proxy     - Start local proxy to deployed agent
 */

const http = require('http');
const https = require('https');
const { execSync, spawn } = require('child_process');
const { URL } = require('url');
const path = require('path');

const LOCAL_PORT = 8080;
const AGENT_NAME = process.env.GLITCH_AGENT_NAME || 'Glitch';
const REGION = process.env.AWS_REGION || 'us-west-2';

// The agent directory where .bedrock_agentcore.yaml lives
const AGENT_DIR = path.resolve(__dirname, '../../agent');

function run(command) {
  try {
    return execSync(command, { encoding: 'utf-8', stdio: ['pipe', 'pipe', 'pipe'], cwd: AGENT_DIR }).trim();
  } catch (error) {
    return null;
  }
}

function runWithOutput(command) {
  try {
    const result = execSync(command, { encoding: 'utf-8', cwd: AGENT_DIR });
    return { success: true, output: result.trim() };
  } catch (error) {
    // Capture both stdout and stderr from the error
    const stdout = error.stdout ? error.stdout.toString() : '';
    const stderr = error.stderr ? error.stderr.toString() : '';
    return { 
      success: false, 
      error: error.message,
      stdout: stdout,
      stderr: stderr,
      output: stdout || stderr || error.message
    };
  }
}

function checkLocalPort() {
  return new Promise((resolve) => {
    const req = http.request({
      hostname: 'localhost',
      port: LOCAL_PORT,
      path: '/ping',
      method: 'GET',
      timeout: 2000
    }, (res) => {
      resolve({ inUse: true, statusCode: res.statusCode });
    });
    
    req.on('error', (err) => {
      if (err.code === 'ECONNREFUSED') {
        resolve({ inUse: false });
      } else {
        resolve({ inUse: true, error: err.message });
      }
    });
    req.on('timeout', () => {
      req.destroy();
      resolve({ inUse: false });
    });
    req.end();
  });
}

function getAgentRuntimeArn() {
  // Get the runtime ARN from agentcore status
  const statusOutput = run(`agentcore status --agent ${AGENT_NAME} --verbose 2>/dev/null`);
  if (!statusOutput) return null;
  
  // Parse the ARN from the output
  const arnMatch = statusOutput.match(/arn:aws:bedrock-agentcore:[^:]+:\d+:runtime\/[^\s"]+/);
  return arnMatch ? arnMatch[0] : null;
}

function getAgentEndpoint() {
  // Try to get endpoint info from agentcore
  const statusOutput = run(`agentcore status --agent ${AGENT_NAME} 2>/dev/null`);
  return statusOutput;
}

/**
 * Invoke the agent using agentcore CLI and return the response
 */
function invokeAgent(payload, sessionId = null) {
  const sessionArg = sessionId ? `--session-id "${sessionId}"` : '';
  const escapedPayload = JSON.stringify(payload).replace(/'/g, "'\\''");
  const cmd = `agentcore invoke '${escapedPayload}' --agent ${AGENT_NAME} ${sessionArg} 2>&1`;
  
  return runWithOutput(cmd);
}

/**
 * Start a proxy server that forwards requests to the deployed agent
 */
function startProxy() {
  console.log('🚀 Starting Glitch Agent Proxy\n');
  console.log('═'.repeat(60));
  console.log(`Agent: ${AGENT_NAME}`);
  console.log(`Region: ${REGION}`);
  console.log(`Local Port: ${LOCAL_PORT}`);
  console.log('═'.repeat(60));
  
  // Track sessions per client
  const sessions = new Map();
  
  const server = http.createServer((req, res) => {
    const url = req.url || '/';
    const method = req.method || 'GET';
    
    // Collect request body
    let body = '';
    req.on('data', chunk => { body += chunk; });
    
    req.on('end', () => {
      // CORS headers
      res.setHeader('Access-Control-Allow-Origin', '*');
      res.setHeader('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS');
      res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization');
      
      if (method === 'OPTIONS') {
        res.writeHead(204);
        res.end();
        return;
      }
      
      const timestamp = new Date().toISOString().split('T')[1].split('.')[0];
      console.log(`[${timestamp}] ${method} ${url}`);
      
      // Health check endpoints
      if (url === '/ping' || url === '/health') {
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ status: 'ok', proxy: true, agent: AGENT_NAME }));
        return;
      }
      
      // API endpoints - invoke agent with special _ui_api payload
      if (url.startsWith('/api/')) {
        const apiPath = url.replace('/api', '');
        let requestBody = null;
        
        try {
          if (body) requestBody = JSON.parse(body);
        } catch (e) {
          res.writeHead(400, { 'Content-Type': 'application/json' });
          res.end(JSON.stringify({ error: 'Invalid JSON body' }));
          return;
        }
        
        // Create a special payload that tells the agent to handle this as an API request
        const payload = {
          _ui_api_request: {
            path: apiPath,
            method: method,
            body: requestBody
          }
        };
        
        const result = invokeAgent(payload);
        
        if (result.success) {
          // Try to extract JSON from the response
          const output = result.output;
          
          // Look for JSON in the output (agentcore invoke adds formatting)
          const jsonMatch = output.match(/\{[\s\S]*\}/);
          if (jsonMatch) {
            try {
              const parsed = JSON.parse(jsonMatch[0]);
              res.writeHead(200, { 'Content-Type': 'application/json' });
              res.end(JSON.stringify(parsed));
              return;
            } catch (e) {
              // Not valid JSON, return as-is
            }
          }
          
          res.writeHead(200, { 'Content-Type': 'application/json' });
          res.end(JSON.stringify({ response: output }));
        } else {
          console.error(`  Error: ${result.error}`);
          if (result.output) {
            console.error(`  Output: ${result.output.substring(0, 500)}`);
          }
          res.writeHead(502, { 'Content-Type': 'application/json' });
          res.end(JSON.stringify({ error: 'Agent invocation failed', details: result.error, output: result.output }));
        }
        return;
      }
      
      // Direct invocation endpoint
      if (url === '/invocations' && method === 'POST') {
        let payload;
        try {
          payload = JSON.parse(body);
        } catch (e) {
          res.writeHead(400, { 'Content-Type': 'application/json' });
          res.end(JSON.stringify({ error: 'Invalid JSON body' }));
          return;
        }
        
        // Get or create session for this client
        const clientId = req.headers['x-client-id'] || 'default';
        let sessionId = sessions.get(clientId);
        
        const result = invokeAgent(payload, sessionId);
        
        if (result.success) {
          // Extract session ID from response if present
          const sessionMatch = result.output.match(/Session:\s*([a-zA-Z0-9-]+)/);
          if (sessionMatch) {
            sessions.set(clientId, sessionMatch[1]);
          }
          
          // Try to parse response
          const jsonMatch = result.output.match(/\{[\s\S]*\}/);
          if (jsonMatch) {
            try {
              const parsed = JSON.parse(jsonMatch[0]);
              res.writeHead(200, { 'Content-Type': 'application/json' });
              res.end(JSON.stringify(parsed));
              return;
            } catch (e) {
              // Not valid JSON
            }
          }
          
          // Return the raw response wrapped in JSON
          res.writeHead(200, { 'Content-Type': 'application/json' });
          res.end(JSON.stringify({ response: result.output }));
        } else {
          res.writeHead(502, { 'Content-Type': 'application/json' });
          res.end(JSON.stringify({ error: 'Agent invocation failed', details: result.error }));
        }
        return;
      }
      
      // Unknown endpoint
      res.writeHead(404, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: 'Not found', path: url }));
    });
  });
  
  server.listen(LOCAL_PORT, 'localhost', () => {
    console.log(`\n✅ Proxy running at http://localhost:${LOCAL_PORT}\n`);
    console.log('Endpoints:');
    console.log('  GET  /ping           Health check');
    console.log('  GET  /api/status     Agent status');
    console.log('  GET  /api/*          API endpoints (via agent)');
    console.log('  POST /invocations    Direct agent invocation');
    console.log('\n' + '═'.repeat(60));
    console.log('Now start the UI in another terminal:');
    console.log('  cd ui && pnpm dev');
    console.log('\nOpen http://localhost:5173');
    console.log('═'.repeat(60));
    console.log('\nPress Ctrl+C to stop the proxy.\n');
  });
  
  server.on('error', (err) => {
    if (err.code === 'EADDRINUSE') {
      console.error(`\n❌ Port ${LOCAL_PORT} is already in use.\n`);
      console.log('Check what\'s using it:');
      console.log(`  lsof -i :${LOCAL_PORT}\n`);
    } else {
      console.error('Server error:', err.message);
    }
    process.exit(1);
  });
  
  // Handle shutdown
  process.on('SIGINT', () => {
    console.log('\n\nShutting down proxy...');
    server.close();
    process.exit(0);
  });
}

/**
 * Check connection status
 */
async function checkStatus() {
  console.log('🔍 Glitch Agent Connection Check\n');
  console.log('═'.repeat(60));
  
  // Check agentcore CLI
  const agentcoreVersion = run('agentcore --version 2>/dev/null');
  if (agentcoreVersion) {
    console.log(`✅ AgentCore CLI: ${agentcoreVersion}`);
  } else {
    console.log('❌ AgentCore CLI not found');
    console.log('\n   Install: pip install bedrock-agentcore-starter-toolkit');
    process.exit(1);
  }
  
  // Check AWS credentials
  const identity = run('aws sts get-caller-identity --query Account --output text 2>/dev/null');
  if (identity) {
    console.log(`✅ AWS Account: ${identity}`);
  } else {
    console.log('❌ AWS credentials not configured');
    console.log('\n   Run: aws configure');
    process.exit(1);
  }
  
  // Check agent status
  console.log(`\nChecking agent "${AGENT_NAME}"...`);
  const status = getAgentEndpoint();
  
  if (status) {
    console.log('✅ Agent found\n');
    console.log(status);
  } else {
    console.log('❌ Agent not found or not deployed');
    console.log('\n   Deploy with: agentcore deploy');
    process.exit(1);
  }
  
  // Check if local port is available
  console.log(`\nChecking localhost:${LOCAL_PORT}...`);
  const portStatus = await checkLocalPort();
  
  if (portStatus.inUse) {
    console.log(`⚠️  Port ${LOCAL_PORT} is in use`);
    if (portStatus.statusCode === 200) {
      console.log('   (Proxy or agent may already be running)');
    }
  } else {
    console.log(`✅ Port ${LOCAL_PORT} is available`);
  }
  
  console.log('\n' + '═'.repeat(60));
  console.log('📋 Next Steps');
  console.log('═'.repeat(60));
  console.log('\n1. Start the proxy:');
  console.log('   cd ui && pnpm proxy');
  console.log('\n2. Start the UI (in another terminal):');
  console.log('   cd ui && pnpm dev');
  console.log('\n3. Open http://localhost:5173\n');
}

// Main
const command = process.argv[2];

if (command === 'proxy') {
  startProxy();
} else {
  checkStatus();
}
