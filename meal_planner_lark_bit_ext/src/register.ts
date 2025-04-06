import {
  basekit,
  Component,
  ParamType,
  FormItems,
} from "@lark-opdev/block-basekit-server-api";

// // OAuth JWT 授权（开发者）
// import jwt from "jsonwebtoken";
// import { v4 as uuidv4 } from "uuid";

// 类型定义，用于 fetch 函数
type FetchFunction = any;

// /**
//  * 生成用于调用 Coze API 的 JWT. Deprecated, 使用 getCozeJwtFromNetlify 替代
//  * https://www.coze.cn/open/docs/developer_guides/oauth_jwt
//  * @param privateKey RSA 私钥字符串
//  * @param cozeAppId Coze App ID
//  * @param keyId Coze App 公钥指纹 (kid)
//  * @param audience Coze API 的 audience (通常是 api.coze.cn)
//  * @param expiresInSeconds Token 有效期（秒），默认为 600 (10分钟)
//  * @returns 生成的 JWT 字符串，如果失败则返回 null
//  */
// const generateCozeJwt = (
//   privateKey: string,
//   cozeAppId: string,
//   keyId: string,
//   audience: string = "api.coze.cn",
//   expiresInSeconds: number = 600
// ): string | null => {
//   try {
//     const nowInSeconds = Math.floor(Date.now() / 1000);
//     const expirationTime = nowInSeconds + expiresInSeconds;

//     const payload = {
//       iat: nowInSeconds, // JWT开始生效的时间，秒级时间戳
//       exp: expirationTime, // JWT过期时间，秒级时间戳
//       jti: uuidv4(), // 随机字符串，防止重放攻击
//       aud: audience, //扣子 API 的Endpoint
//       iss: cozeAppId, // OAuth 应用的 ID
//     };

//     const headers = {
//       alg: "RS256", // 固定为RS256
//       typ: "JWT", // 固定为JWT
//       kid: keyId, // OAuth 应用的公钥指纹
//     };

//     const token = jwt.sign(payload, privateKey, {
//       algorithm: "RS256",
//       header: headers, // 将 header 放在 sign options 中
//     });

//     console.log("成功生成 Coze JWT");
//     return token;
//   } catch (error) {
//     console.error("生成 Coze JWT 失败:", error);
//     return null;
//   }
// };

/**
 * 从远程 Netlify 函数服务获取 Coze JWT
 * privateKey 以 Base64 编码保存于 Netlify 环境变量 COZE_PRIVATE_KEY
 * @param fetchFunction 用于发送请求的 fetch 函数
 * @param cozeAppId Coze APP ID
 * @param cozeKeyId OAuth APP 公钥指纹（kid）
 * @param cozeAudience Coze API 的 Endpoint，默认为 api.coze.cn
 * @param expiresIn JWT 有效期（秒），默认 600 秒（10分钟）
 * @param serviceUrl 远程 Netlify 函数服务 URL，默认为 https://generatecozejwt.netlify.app/.netlify/functions/generate-coze-jwt
 * @returns 包含 token 字段的对象，如果失败则返回 null
 */
async function getCozeJwtFromNetlify(
  fetchFunction: any,
  cozeAppId: string,
  cozeKeyId: string,
  cozeAudience: string = "api.coze.cn",
  expiresIn: number = 600,
  serviceUrl: string = "https://generatecozejwt.netlify.app/.netlify/functions/generate-coze-jwt"
): Promise<{ token: string } | null> {
  try {
    console.log(
      `开始请求 Coze JWT，应用ID: ${cozeAppId}, 密钥ID: ${cozeKeyId}`
    );

    const response = await fetchFunction(serviceUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        cozeAppId,
        keyId: cozeKeyId,
        audience: cozeAudience,
        expiresIn,
      }),
    });

    if (!response.ok) {
      const errorText = await response.text();
      console.error(`JWT服务响应错误: ${response.status}`, errorText);
      return null;
    }

    const tokenData = await response.json();

    if (!tokenData.token) {
      console.error("JWT服务未返回有效token", tokenData);
      return null;
    }

    console.log("成功获取 Coze JWT");
    return { token: tokenData.token };
  } catch (error) {
    console.error("获取 Coze JWT 过程中发生错误:", error);
    return null;
  }
}

/**
 * 使用 JWT 获取 Coze Access Token
 * https://www.coze.cn/open/docs/developer_guides/oauth_jwt
 * @param fetchFunction Basekit 提供的 fetch 函数
 * @param cozeJwtToken 用于认证的 JWT
 * @param tokenUrl Coze OAuth Token 端点 URL
 * @returns 包含 access_token 和 expires_in 的对象，失败则返回 null
 */
const getCozeAccessToken = async (
  fetchFunction: FetchFunction, // 使用导入的 Fetch 类型或 any
  cozeJwtToken: string,
  tokenUrl: string = "https://api.coze.cn/api/permission/oauth2/token" // 默认 URL
): Promise<{ accessToken: string; expiresIn: number } | null> => {
  try {
    const tokenRequestBody = {
      duration_seconds: 86399, // 请求的 access_token 有效期
      grant_type: "urn:ietf:params:oauth:grant-type:jwt-bearer",
    };

    console.log("开始请求 Coze Access Token...");
    const response = await fetchFunction(tokenUrl, {
      // 使用传入的 fetch 函数
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${cozeJwtToken}`,
      },
      body: JSON.stringify(tokenRequestBody),
    });

    console.log("Coze Token API 响应状态:", response.status);

    if (!response.ok) {
      const errorText = await response.text();
      console.error("获取 Coze Access Token 失败:", response.status, errorText);
      // 可以选择抛出错误或返回 null
      // throw new Error(`获取 Coze Access Token 失败: ${response.status} - ${errorText}`);
      return null;
    }

    const tokenData = await response.json();
    console.log("成功获取 Coze Access Token Data");

    if (tokenData && tokenData.access_token && tokenData.expires_in) {
      console.log(
        `获取到的 Access Token: ${tokenData.access_token}, 过期时间戳: ${tokenData.expires_in}`
      );
      return {
        accessToken: tokenData.access_token,
        expiresIn: tokenData.expires_in,
      };
    } else {
      console.error("Coze Token API 返回的数据格式不正确:", tokenData);
      // throw new Error("获取 Coze Access Token 成功，但返回数据格式不正确");
      return null;
    }
  } catch (error) {
    console.error("请求 Coze Access Token 时发生网络或解析错误:", error);
    // 可以选择抛出错误或返回 null
    // throw error; // 重新抛出错误，让调用者处理
    return null;
  }
};

/**
 * 使用 Access Token 调用 Coze 工作流 API
 * https://www.coze.cn/open/docs/developer_guides/workflow_run
 * @param fetchFunction Basekit 提供的 fetch 函数
 * @param accessToken Coze Access Token
 * @param workflowId 要运行的工作流 ID
 * @param parameters 工作流所需的输入参数对象
 * @param apiUrl Coze 工作流运行 API 端点 URL
 * @returns Coze API 的响应数据，如果请求失败或 Coze 返回错误码，则返回 null
 */
const runCozeWorkflow = async (
  fetchFunction: FetchFunction,
  accessToken: string,
  workflowId: string,
  parameters: Record<string, any>, // 使用 Record<string, any> 或更具体的类型
  apiUrl: string = "https://api.coze.cn/v1/workflow/run" // 默认工作流运行 API URL
): Promise<any | null> => {
  // 返回类型可以是 any 或更具体的 Coze 响应类型
  try {
    const requestBody = {
      workflow_id: workflowId,
      parameters: parameters,
    };

    console.log(
      `准备调用 Coze 工作流: ${workflowId}，参数:`,
      JSON.stringify(parameters)
    );
    console.log(`API 端点: ${apiUrl}`);

    const response = await fetchFunction(apiUrl, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${accessToken}`, // 使用 Access Token
        "Content-Type": "application/json",
      },
      body: JSON.stringify(requestBody),
    });

    console.log(`Coze 工作流 API (${workflowId}) 响应状态:`, response.status);

    if (!response.ok) {
      const errorText = await response.text();
      console.error(
        `调用 Coze 工作流 (${workflowId}) 失败:`,
        response.status,
        errorText
      );
      // 可以尝试解析错误文本，看是否是 Coze 的标准错误格式
      try {
        const errorJson = JSON.parse(errorText);
        console.error("Coze 工作流错误详情:", errorJson);
        // 可以根据需要返回 errorJson 或特定错误信息
      } catch (parseError) {
        // 如果错误响应不是 JSON 格式
        console.error("无法解析 Coze 错误响应:", parseError);
      }
      return null; // 请求不成功，返回 null
    }

    const responseData = await response.json();
    console.log(`Coze 工作流 (${workflowId}) 响应数据:`, responseData);

    // 检查 Coze 返回的业务错误码 code
    if (responseData.code !== 0) {
      console.error(
        `Coze 工作流 (${workflowId}) 返回业务错误:`,
        responseData.code,
        responseData.msg
      );
      // 根据需要，可以返回整个 responseData 或只返回 null/错误信息
      return null; // Coze 返回非 0 code，表示业务逻辑失败
    }

    // 成功，返回 Coze 的响应数据
    return responseData;
  } catch (error) {
    console.error(
      `调用 Coze 工作流 (${workflowId}) 时发生网络或解析错误:`,
      error
    );
    return null; // 发生异常，返回 null
  }
};

const formFieldsMap = {
  // --- 飞书表格参数 ---
  app_token: "表格token",
  dishes_table_id: "表ID：01-菜品管理",
  meal_config_table_id: "表ID：05-餐类配置",
  nutrition_std_table_id: "表ID：95-营养标准-每日",
  meal_nutrition_std_table_id: "表ID：06-营养标准-每餐",
  sys_config_table_id: "表ID：07-系统配置",
  plan_table_id: "表ID：08-排餐方案-总体",
  plan_daily_table_id: "表ID：09-排餐方案-每天",
  plan_meal_table_id: "表ID：10-排餐方案-每餐",
  // --- Coze 认证参数 ---
  // cozePrivateKey: "Coze App 私钥（注意末尾换行符）", // 以 Base64 编码保存于 Netlify 环境变量 COZE_PRIVATE_KEY
  cozeAppId: "OAuth 应用的 ID",
  cozeKeyId: "OAuth 应用的公钥指纹",
  cozeAudience: "扣子 API 的Endpoint（api.coze.cn）",
  cozeTokenUrl:
    "通过 JWT 获取 Oauth Access Token 的请求地址（https://api.coze.cn/api/permission/oauth2/token）",
  // --- Coze 工作流参数 ---
  cozeWorkflowId: "要运行的 Coze 工作流 ID",
  cozeWorkflowApiUrl:
    "Coze 工作流运行 API 端点 (https://api.coze.cn/v1/workflow/run)",
};

const generateFormItems = (fieldsMap: Record<string, string>): FormItems => {
  return Object.entries(fieldsMap).map(([itemId, label]) => ({
    itemId,
    label,
    required: true,
    component: Component.Input,
    componentProps: {
      mode: "textarea",
      placeholder: `请输入${label}`,
    },
  })) as FormItems;
};

const formItems = generateFormItems(formFieldsMap);

// https://open.feishu.cn/document/uAjLw4CM/uYjL24iN/base-extensions/base-automation-extensions/data-type/context
const executeAction = async function (args: any, context: any) {
  try {
    const {
      // --- 飞书表格参数 ---
      app_token,
      dishes_table_id,
      meal_config_table_id,
      nutrition_std_table_id,
      meal_nutrition_std_table_id,
      sys_config_table_id,
      plan_table_id,
      plan_daily_table_id,
      plan_meal_table_id,
      // --- Coze 认证参数 ---
      // cozePrivateKey, // 以 Base64 编码保存于 Netlify 环境变量 COZE_PRIVATE_KEY
      cozeAppId,
      cozeKeyId,
      cozeAudience,
      cozeTokenUrl,
      // --- Coze 工作流参数 ---
      cozeWorkflowId,
      cozeWorkflowApiUrl,
    } = args;

    // 从context中获取授权信息
    const { tenantAccessToken } = context;
    if (!tenantAccessToken) {
      console.log("未找到授权信息");
      return {
        message: "未找到授权信息，请确保已正确授权",
        workflowResult: "",
      };
    }

    const token = tenantAccessToken;

    // 记录 authorization 信息
    // 注：authorization 不是 tenant_access_token or user_access_token
    // 目前，飞书 API 只支持 tenant_access_token 授权
    // const { type, token } = authorization || {};
    // console.log("授权类型:", type);
    // console.log("授权令牌:", token);

    // 检查授权类型是否为user_access_token
    // if (type !== "user_access_token") {
    //   console.log("授权类型不匹配，需要user_access_token类型，当前类型:", type);
    //   return {
    //     message: "授权类型不匹配，请使用用户身份授权",
    //     workflowResult: "",
    //   };
    // }

    // 将授权信息添加到参数中
    const user_access_token = token;

    const { fetch } = context;

    // --- 1. 生成 Coze JWT ---
    const jwtResult = await getCozeJwtFromNetlify(
      fetch, // 使用 context 提供的 fetch
      cozeAppId,
      cozeKeyId,
      cozeAudience || undefined,
      600 // 默认10分钟有效期
    );
    if (!jwtResult) {
      return {
        message: "获取 Coze JWT 令牌失败",
        workflowResult: "",
      };
    }
    const cozeJwtToken = jwtResult.token;
    // --- 结束生成 Coze JWT ---

    // --- 2. 使用 JWT 获取 Coze Access Token ---
    // 使用传入的 cozeTokenUrl，如果为空或未提供，则使用 getCozeAccessToken 函数中的默认值
    const tokenInfo = await getCozeAccessToken(
      fetch,
      cozeJwtToken,
      cozeTokenUrl || undefined
    );
    if (!tokenInfo) {
      // getCozeAccessToken 内部已经打印了错误日志
      return { message: "获取 Coze Access Token 失败", workflowResult: "" };
    }
    const { accessToken: cozeAccessToken, expiresIn } = tokenInfo;
    // --- 结束获取 Coze Access Token ---

    // --- 3. 运行 Coze 工作流 ---
    const workflowParameters = {
      app_token: app_token,
      dishes: dishes_table_id,
      meal_config: meal_config_table_id,
      nutrition_std: nutrition_std_table_id,
      meal_nutrition_std: meal_nutrition_std_table_id,
      sys_config: sys_config_table_id,
      plan: plan_table_id,
      plan_daily: plan_daily_table_id,
      plan_meal: plan_meal_table_id,
      user_access_token: user_access_token,
    }; // Coze 要求输入变量名长度不超过 20 个字符
    const workflowResult = await runCozeWorkflow(
      fetch,
      cozeAccessToken,
      cozeWorkflowId, // 从 args 获取
      workflowParameters, // 准备好的参数
      cozeWorkflowApiUrl || undefined // 从 args 获取，或使用默认 URL
    );
    if (!workflowResult) {
      // runCozeWorkflow 内部已打印错误
      return { message: "调用 Coze 工作流失败", workflowResult: "" };
    }
    console.log("Coze 工作流成功执行，返回数据:", workflowResult);
    // --- 结束运行 Coze 工作流 ---

    // 返回转换后的数据
    return {
      message: "操作已执行，请查看 Coze 工作流返回信息",
      workflowResult: JSON.stringify(workflowResult),
    };
  } catch (error) {
    console.error("执行动作时发生错误:", error);
    return {
      message: "执行动作时发生错误:" + error,
      workflowResult: "",
    };
  }
};

// https://open.feishu.cn/document/uAjLw4CM/uYjL24iN/base-extensions/base-automation-extensions/base-automation-extension-development-guide
// https://open.feishu.cn/document/uAjLw4CM/uYjL24iN/base-extensions/base-automation-extensions/api/addaction
basekit.addAction({
  useTenantAccessToken: true,
  formItems,
  // 使用定义好的执行函数
  execute: executeAction,
  // 定义节点出参
  resultType: {
    // 声明返回为对象
    type: ParamType.Object,
    properties: {
      // 声明 message 属性
      message: {
        // 声明 message 字段类型为 string
        type: ParamType.String,
        // 声明在节点 UI 上展示的文案为
        label: "回调信息",
      },
      workflowResult: {
        type: ParamType.String,
        label: "Coze 工作流返回结果",
      },
    },
  },
});

export default basekit;
