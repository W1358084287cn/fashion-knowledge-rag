-- ============================================================
-- 示例：商品与售后规则表结构（含演示数据）
-- 说明：本文件用于演示 SQL 脚本自动解析为知识切片
-- ============================================================
CREATE TABLE `goods_demo` (
  `goods_no` VARCHAR(50) COMMENT '商品款号',
  `name` VARCHAR(200) COMMENT '商品名称',
  `fabric` VARCHAR(500) COMMENT '面料成分',
  `sizes` VARCHAR(200) COMMENT '可选尺码',
  `care` VARCHAR(500) COMMENT '保养方式',
  `after_sale` VARCHAR(500) COMMENT '售后政策',
  `activity` VARCHAR(500) COMMENT '活动信息'
);

INSERT INTO `goods_demo` (`goods_no`, `name`, `fabric`, `sizes`, `care`, `after_sale`, `activity`) VALUES
('FY2026-001', '羊毛双面呢大衣', '羊毛90%羊绒10%', 'S/M/L/XL', '建议干洗，悬挂存放', '30天质量问题免费退换', '会员日9折'),
('FY2026-002', '真丝印花衬衫', '桑蚕丝100%', 'S/M/L', '30℃以下冷水手洗，阴干', '7天无理由退换', '新品上市'),
('FY2026-003', '高腰直筒牛仔裤', '棉98%氨纶2%', '26/27/28/29', '翻面冷水机洗，避免混洗', '7天无理由退换', '第二件8折');

CREATE TABLE `after_sale_rule` (
  `rule_id` INT COMMENT '规则编号',
  `rule_name` VARCHAR(100) COMMENT '规则名称',
  `days` INT COMMENT '时效天数',
  `description` VARCHAR(500) COMMENT '规则说明'
);

INSERT INTO `after_sale_rule` (`rule_id`, `rule_name`, `days`, `description`) VALUES
(1, '七天无理由退换', 7, '签收7天内不影响二次销售可退换，运费买家承担'),
(2, '质量问题退换', 30, '签收30天内质量问题免费退换，运费商家承担'),
(3, '价保服务', 15, '签收15天内同款降价可申请补差价');

-- 资料来源：https://www.example-fashion.com/schema
-- 客服邮箱：service@example-fashion.com
