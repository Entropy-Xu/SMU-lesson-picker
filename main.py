import requests
import time
import json
import logging
from bs4 import BeautifulSoup
import getpass
import os
import re
import urllib3
from urllib.parse import urljoin

# 禁用SSL证书验证的警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("course_sniper.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("SMU-CourseSniper")

class SMUCourseSniper:
    def __init__(self):
        """初始化抢课脚本"""
        self.cas_url = "https://cas.shmtu.edu.cn/cas/login"
        self.captcha_url = "https://cas.shmtu.edu.cn/cas/captcha"
        self.jwxt_base_url = "https://jwxt.shmtu.edu.cn"
        self.elect_course_url = "https://jwxt.shmtu.edu.cn/shmtu/stdElectCourse!defaultPage.action"
        self.elect_index_url = "https://jwxt.shmtu.edu.cn/shmtu/stdElectCourse!index.action"  # 选课主页URL
        self.session = requests.Session()
        # 禁用 SSL 证书验证
        self.session.verify = False
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9'
        })
        self.logged_in = False
        self.profile_id = None
        self.elec_session_time = None

    def get_captcha(self):
        """获取验证码图片"""
        try:
            response = self.session.get(self.captcha_url)
            response.raise_for_status()

            # 保存验证码图片
            with open('captcha.jpg', 'wb') as f:
                f.write(response.content)

            logger.info("验证码已保存至captcha.jpg，请查看并输入")
            captcha_code = input("请输入验证码: ")
            return captcha_code
        except Exception as e:
            logger.error(f"获取验证码失败: {str(e)}")
            return None

    def get_login_params(self):
        """获取登录页面的必要参数"""
        try:
            response = self.session.get(self.cas_url)
            response.raise_for_status()

            # 使用BeautifulSoup解析登录页面
            soup = BeautifulSoup(response.text, 'html.parser')

            # 提取execution参数
            execution = soup.find('input', {'name': 'execution'})['value'] if soup.find('input', {'name': 'execution'}) else None

            return {
                'execution': execution
            }
        except Exception as e:
            logger.error(f"获取登录参数失败: {str(e)}")
            return None

    def login(self, username, password):
        """登录教务系统"""
        # 获取登录所需参数
        login_params = self.get_login_params()
        if not login_params:
            return False

        # 获取验证码
        validate_code = self.get_captcha()
        if not validate_code:
            return False

        login_data = {
            'username': username,
            'password': password,
            'validateCode': validate_code,
            '_eventId': 'submit',
            'geolocation': ''
        }

        # 添加execution参数
        if login_params.get('execution'):
            login_data['execution'] = login_params['execution']
        else:
            logger.error("无法获取execution参数，登录可能失败")
            return False

        try:
            response = self.session.post(self.cas_url, data=login_data)
            response.raise_for_status()

            # 检查是否登录成功
            if "登录成功" in response.text or "欢迎" in response.text or "index" in response.url:
                logger.info(f"用户 {username} 登录成功")
                self.logged_in = True
                return True
            else:
                # 检查是否有错误信息
                soup = BeautifulSoup(response.text, 'html.parser')
                errors = soup.find('div', {'class': 'errors'})
                if errors:
                    logger.error(f"登录失败: {errors.text.strip()}")
                else:
                    logger.error(f"登录失败，请检查账号密码和验证码")
                return False

        except Exception as e:
            logger.error(f"登录出错: {str(e)}")
            return False

    def get_election_params(self):
        """获取选课必要参数"""
        try:
            # 获取选课页面以提取必要参数
            response = self.session.get(self.elect_course_url)
            response.raise_for_status()

            # 提取选课页面中的profileId
            profile_id_match = re.search(r'electionProfile\.id=(\d+)', response.text)
            if profile_id_match:
                self.profile_id = profile_id_match.group(1)
                logger.info(f"获取到profileId: {self.profile_id}")
            else:
                logger.error("无法获取选课参数profileId")
                return False

            # 生成选课时间戳
            self.elec_session_time = time.strftime("%Y%m%d%H%M%S", time.localtime())
            return True

        except Exception as e:
            logger.error(f"获取选课参数失败: {str(e)}")
            return False

    def select_course(self, course_id):
        """选择指定课程"""
        if not self.logged_in:
            logger.error("请先登录")
            return False

        # 如果没有设置profile_id和elec_session_time才获取
        if not self.profile_id or not self.elec_session_time:
            if not self.get_election_params():
                return False

        # 第一步：先访问选课主页面，确保会话有效
        try:
            default_page_url = f"{self.jwxt_base_url}/shmtu/stdElectCourse!defaultPage.action?electionProfile.id={self.profile_id}"
            default_response = self.session.get(default_page_url)
            default_response.raise_for_status()

            # 确保页面加载成功
            if "选课" not in default_response.text:
                logger.warning("无法正确加载选课页面，可能需要重新登录")
                return False

            logger.info("已成功加载选课页面")

            # 重新生成时间戳以确保有效性
            self.elec_session_time = time.strftime("%Y%m%d%H%M%S", time.localtime())

            # 第二步：发送选课请求
            batch_url = f"{self.jwxt_base_url}/shmtu/stdElectCourse!batchOperator.action"

            # 模拟真实浏览器请求头
            headers = {
                'X-Requested-With': 'XMLHttpRequest',
                'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                'Origin': self.jwxt_base_url,
                'Referer': default_page_url,
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
                'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
                'Connection': 'keep-alive'
            }

            # 构建选课数据，与浏览器真实请求完全一致
            form_data = {
                'profileId': self.profile_id,
                'elecSessionTime': self.elec_session_time,
                'operator0': f"{course_id}:true:0"
            }

            # 发送请求，设置超时以避免长时间挂起
            response = self.session.post(
                batch_url,
                data=form_data,
                headers=headers,
                timeout=10
            )

            # 检查响应
            if response.status_code != 200:
                logger.error(f"选课请求返回异常状态码: {response.status_code}")
                return False

            # 如果返回HTML页面而非JSON数据，可能是选课失败或服务器错误
            if "<!DOCTYPE html" in response.text or "<html" in response.text:
                if "NullPointerException" in response.text:
                    logger.error("服务器发生空指针异常，可能是请求参数格式不正确或服务器bug")
                    # 记录请求详情以便调试
                    logger.debug(f"请求URL: {batch_url}")
                    logger.debug(f"请求数据: {form_data}")
                    return False
                else:
                    # ���析失败原因并显示给用户
                    # 同时将完整原始响应记录到日志
                    logger.debug(f"选课失败，原始响应:\n{response.text}")
                    failure_reason = self.parse_failure_reason(response.text)
                    logger.warning(failure_reason)
                    print(f"\n{failure_reason}\n")  # 直接在控制台显示失败原因
                    return False

            # 检查选课结果
            result_text = response.text.strip()
            logger.debug(f"选课响应: {result_text}")

            if "成功" in result_text:
                success_msg = f"成功选上课程 {course_id}"
                logger.info(success_msg)
                print(f"\n{success_msg}\n")
                return True
            elif "已选" in result_text:
                already_msg = f"课程 {course_id} 已经选过"
                logger.info(already_msg)
                print(f"\n{already_msg}\n")
                return True
            else:
                error_msg = f"选课失败: {result_text[:200]}"
                logger.warning(error_msg)
                print(f"\n{error_msg}\n")
                return False

        except requests.exceptions.Timeout:
            logger.error("选课请求超时")
            return False
        except Exception as e:
            logger.error(f"选课过程出错: {str(e)}")
            return False

    def auto_snipe(self, course_ids, interval=1, max_attempts=100):
        """自动抢课"""
        if not self.logged_in:
            logger.error("请先登录")
            return

        # 如果没有设置profile_id和elec_session_time才获取选课参数
        if not self.profile_id or not self.elec_session_time:
            if not self.get_election_params():
                logger.error("无法获取选课参数，抢课终止")
                return
        else:
            logger.info(f"使用已选择的选课轮次，profileId: {self.profile_id}")

        remaining_courses = set(course_ids)
        attempt = 0

        logger.info(f"开始抢课，目标课程: {course_ids}")

        while remaining_courses and attempt < max_attempts:
            attempt += 1
            logger.info(f"第 {attempt}/{max_attempts} 次尝试")

            current_courses = list(remaining_courses)
            for course_id in current_courses:
                if self.select_course(course_id):
                    remaining_courses.remove(course_id)

            if remaining_courses:
                time.sleep(interval)
                # 每隔10次刷新选课时间戳，但保留profileId
                if attempt % 10 == 0:
                    self.elec_session_time = time.strftime("%Y%m%d%H%M%S", time.localtime())
                    logger.info(f"已刷新选课时间戳: {self.elec_session_time}")

        if not remaining_courses:
            logger.info("所有课程已抢到!")
        else:
            logger.warning(f"达到最大尝试次数，未能抢到的课程: {remaining_courses}")

    def get_all_election_profiles(self):
        """获取所有可用的选课轮次及对应的profileId"""
        try:
            # 获取选课主页
            response = self.session.get(self.elect_index_url)
            response.raise_for_status()

            # 使用BeautifulSoup解析页面
            soup = BeautifulSoup(response.text, 'html.parser')

            # 查找所有选课链接
            election_profiles = []
            links = soup.find_all('a', href=re.compile(r'electionProfile\.id=\d+'))

            for link in links:
                # 提取profileId
                profile_match = re.search(r'electionProfile\.id=(\d+)', link['href'])
                if profile_match:
                    profile_id = profile_match.group(1)

                    # 获取选课名称（在父级元素的前几个兄弟节点中）
                    tr = link.find_parent('tr')
                    if tr:
                        name_td = tr.find_all('td')[1] if len(tr.find_all('td')) > 1 else None
                        name = name_td.text.strip() if name_td else "未知选课轮次"

                        election_profiles.append({
                            'profile_id': profile_id,
                            'name': name
                        })

            if election_profiles:
                logger.info(f"找到{len(election_profiles)}个选课轮次")
                return election_profiles
            else:
                logger.warning("未找到任何选课轮次")
                return []

        except Exception as e:
            logger.error(f"获取选课信息失败: {str(e)}")
            return []

    def select_election_profile(self):
        """让用户选择要进行的选课类型"""
        profiles = self.get_all_election_profiles()

        if not profiles:
            logger.error("无法获取选课信息")
            return False

        print("\n可用的选课轮次:")
        for i, profile in enumerate(profiles):
            print(f"{i+1}. {profile['name']} (ID: {profile['profile_id']})")

        try:
            choice = int(input("\n请选择要进行的选课类型 (输入序号): ")) - 1
            if 0 <= choice < len(profiles):
                self.profile_id = profiles[choice]['profile_id']
                logger.info(f"已选择: {profiles[choice]['name']} (ID: {self.profile_id})")

                # 生成选课时间戳
                self.elec_session_time = time.strftime("%Y%m%d%H%M%S", time.localtime())
                return True
            else:
                logger.error("无效的选择")
                return False
        except ValueError:
            logger.error("请输入有效的数字")
            return False

    def parse_failure_reason(self, html_response):
        """解析选课失败原因，从HTML响应中提取有用信息"""
        try:
            # 检查是否是HTML/CSS内容
            if html_response and ("<style" in html_response or "<html" in html_response):
                # 首先尝试提取 "选课失败:" 后面的文本
                failure_match = re.search(r'选课失败:\s*([^<]+)', html_response)
                if failure_match and failure_match.group(1).strip():
                    return f"选课失败: {failure_match.group(1).strip()}"

                # 使用BeautifulSoup解析HTML
                soup = BeautifulSoup(html_response, 'html.parser')

                # 删除所有样式和脚本标签
                for tag in soup(['style', 'script']):
                    tag.decompose()

                # 尝试查找错误信息
                error_div = soup.find('div', {'class': 'error'}) or soup.find('div', style=lambda s: s and 'color:red' in s)
                if error_div:
                    error_text = error_div.get_text(strip=True)
                    if error_text:
                        return f"选课失败: {error_text}"

                # 尝试查找弹窗提示内容
                alert_div = soup.find('div', {'class': 'co'}) or soup.find('div', id=lambda i: i and 'alert' in i.lower())
                if alert_div:
                    alert_text = alert_div.get_text(strip=True)
                    if alert_text and len(alert_text) > 5:
                        return f"选课失败: {alert_text}"

                # 提取正文内容，查找可能的错误消息
                body = soup.find('body')
                if body:
                    # 移除所有可能存在的隐藏元素
                    for hidden in body.find_all(style=lambda s: s and ('display:none' in s or 'visibility:hidden' in s)):
                        hidden.decompose()

                    # 获取文本内容
                    text = body.get_text(separator=' ', strip=True)

                    # 查找可能的错误信息短语
                    for phrase in ["选课失败", "失败原因", "错误", "人数已满", "冲突", "请重试"]:
                        if phrase in text:
                            # 提取包含该短语的句子或短文本
                            position = text.find(phrase)
                            start = max(0, position - 20)
                            end = min(len(text), position + 100)
                            context = text[start:end].strip()
                            return f"选课失败: {context}..."

                # 如果无法从HTML中提取���效信息，返回简化消息
                return "选课失败: 服务器返回了HTML页面，无法解析具体原因，请稍后再试"

            # 如果是纯文本响应
            elif html_response:
                if "选课失败" in html_response:
                    # 尝试获取"选课失败:"后面的内容
                    match = re.search(r'选课失败:\s*(.*)', html_response)
                    if match:
                        return f"选课失败: {match.group(1).strip()}"
                return f"选课失败: {html_response.strip()}"
            else:
                return "选课失败: 服务器未返回任何信息"

        except Exception as e:
            logger.error(f"解析失败原因出错: {str(e)}")
            return f"无法解析选课失败原因: {str(e)}"


def main():
    sniper = SMUCourseSniper()

    username = input("请输入学号: ")
    password = getpass.getpass("请输入密码: ")

    if sniper.login(username, password):
        # 输入要抢的课程ID
        course_ids = input("请输入要抢的课程ID（多个ID以逗号分隔）: ").split(",")
        course_ids = [cid.strip() for cid in course_ids]

        # 设置抢课参数
        interval = float(input("请输入重试间隔（秒，默认1秒）: ") or "1")
        max_attempts = int(input("请输入最大尝试次数（默认100）: ") or "100")

        # 选择选课轮次
        if not sniper.select_election_profile():
            logger.error("选课轮次选择失败，程序退出")
            return

        # 开始抢课
        sniper.auto_snipe(course_ids, interval, max_attempts)


if __name__ == "__main__":
    main()