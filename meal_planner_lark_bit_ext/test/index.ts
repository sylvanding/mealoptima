import {
  testAction,
  createActionContext,
} from "@lark-opdev/block-basekit-server-api";

async function test() {
  const actionContext = await createActionContext({
    // 飞书多维表格插件只能使用 tenant_access_token 授权，以`t-`开头
    tenantAccessToken: "t-g10444dk5VESG7PLVXCK2YSWCOWBSKEMC56MBFVH",
  });

  testAction(
    {
      // --- 飞书表格参数 ---
      app_token: "PgDqbJoYoaTjtNskSEkcv9WJn1d",
      dishes_table_id: "tblaJ81rpxNpToh5",
      meal_config_table_id: "tbl5nmeBDFE68SVB",
      nutrition_std_table_id: "tblS33TCJvoEKlR2",
      meal_nutrition_std_table_id: "tblSwvNEzVciVDwQ",
      sys_config_table_id: "tblPJqlBBmCSp2fG",
      plan_table_id: "tblmnGQVnYVKYa0Y",
      plan_daily_table_id: "tblHCDc76F9JFpJk",
      plan_meal_table_id: "tblfl0qz6J090E6E",
      // --- Coze 认证参数 ---
      // cozePrivateKey 以 Base64 编码保存于 Netlify 环境变量 COZE_PRIVATE_KEY
      cozeAppId: "1117928111478",
      cozeKeyId: "6zOqE4y0aN-XGd_EouuUKfjvj2GSJ8LjaQQMBtdYz4g",
      cozeAudience: "api.coze.cn",
      cozeTokenUrl: "https://api.coze.cn/api/permission/oauth2/token",
      // --- Coze 工作流参数 ---
      cozeWorkflowId: "7487502311633616923",
      cozeWorkflowApiUrl: "https://api.coze.cn/v1/workflow/run",
    },
    actionContext
  );
}

test();
